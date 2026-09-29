import hashlib
import re
import uuid
import zipfile
from pathlib import Path

from defusedxml.ElementTree import fromstring


class InvalidFile(ValueError):
    pass


MIMES = {
    "md": {"text/markdown", "text/plain"}, "txt": {"text/plain"}, "pdf": {"application/pdf"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"}
}


def storage_path(settings, key):
    if not key or "\\" in key or Path(key).is_absolute():
        raise InvalidFile("storage_key_invalid")
    root = settings.storage_path.resolve()
    target = (root / key).resolve()
    if not target.is_relative_to(root) or target == root:
        raise InvalidFile("storage_key_invalid")
    return target


def validate_file(path, filename, content_type, settings):
    if not filename or len(filename) > 200 or re.search(r'[\\/:\x00-\x1f]', filename) or filename in {".", ".."}:
        raise InvalidFile("filename_invalid")
    fmt = Path(filename).suffix.lower().lstrip(".")
    if fmt not in MIMES:
        raise InvalidFile("format_unsupported")
    mime = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if mime not in MIMES[fmt] | {"application/octet-stream"}:
        raise InvalidFile("mime_mismatch")
    if fmt in {"md", "txt"}:
        with path.open("rb") as handle:
            if handle.read(5).startswith((b"%PDF", b"PK\x03\x04")):
                raise InvalidFile("format_mismatch")
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                while chunk := handle.read(1024 * 1024):
                    if "\x00" in chunk:
                        raise InvalidFile("text_binary")
        except UnicodeError as exc:
            raise InvalidFile("text_requires_utf8") from exc
    elif fmt == "pdf":
        import pymupdf
        try:
            with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as document:
                if document.needs_pass or len(document) > settings.extraction_max_pages:
                    raise InvalidFile("pdf_encrypted_or_too_many_pages")
        except InvalidFile:
            raise
        except Exception as exc:
            raise InvalidFile("pdf_corrupt") from exc
    else:
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(item.file_size for item in entries) > settings.docx_expanded_max_bytes:
                    raise InvalidFile("docx_expansion_limit")
                for item in entries:
                    if (item.flag_bits & 1 or "\\" in item.filename or item.filename.startswith("/")
                        or ".." in Path(item.filename).parts or re.match(r"^[a-zA-Z]:", item.filename)
                        or item.file_size > max(1, item.compress_size) * 1000):
                        raise InvalidFile("docx_archive_unsafe")
                if "word/document.xml" not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                    raise InvalidFile("docx_structure_invalid")
                types = fromstring(archive.read("[Content_Types].xml"))
                document = fromstring(archive.read("word/document.xml"))
                if document.tag != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document":
                    raise InvalidFile("docx_structure_invalid")
                if not any(node.attrib.get("PartName") == "/word/document.xml" and
                           node.attrib.get("ContentType") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                           for node in types):
                    raise InvalidFile("docx_content_type_invalid")
                if any("vbaProject" in item.filename for item in entries):
                    raise InvalidFile("docx_macros_unsupported")
        except InvalidFile:
            raise
        except Exception as exc:
            raise InvalidFile("docx_corrupt") from exc
    return fmt


def save_upload(file, filename, content_type, settings):
    directory = settings.storage_path / "originals"
    directory.mkdir(parents=True, exist_ok=True)
    key = "originals/" + str(uuid.uuid4())
    target = storage_path(settings, key)
    digest, size = hashlib.sha256(), 0
    try:
        with target.open("xb") as handle:
            while chunk := file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.upload_max_bytes:
                    raise InvalidFile("upload_too_large")
                digest.update(chunk)
                handle.write(chunk)
        fmt = validate_file(target, filename, content_type, settings)
        return key, digest.hexdigest(), size, fmt
    except BaseException:
        target.unlink(missing_ok=True)
        raise
