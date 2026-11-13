"""Numeric recognition shared by grounding and figures. Extracted verbatim."""
import re
import unicodedata


_UNITS = ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince "
          "dieciseis diecisiete dieciocho diecinueve veinte veintiuno veintidos veintitres veinticuatro "
          "veinticinco veintiseis veintisiete veintiocho veintinueve").split()
NUMBER_WORDS = {word: value for value, word in enumerate(_UNITS)} | {
    "veintiun": 21, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
    "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600, "setecientos": 700,
    "ochocientos": 800, "novecientos": 900, "mil": 1000, "medio": 0.5, "media": 0.5,
    "doble": 2, "triple": 3, "mitad": 0.5, "docena": 12, "decena": 10, "centenar": 100}
del NUMBER_WORDS["uno"]  # "uno/una/un" are mostly articles; digits still count.


def numbers(text):
    """Numeric values stated in text, as digits or Spanish number words."""
    text = text.replace("½", ".5").replace("¼", ".25").replace("¾", ".75")
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    found = set()
    for match in re.finditer(r"\d+(?:[.,]\d+)*", plain):
        value = match.group()
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
            value = value.replace(".", "")
        value = value.replace(",", ".")
        try:
            found.add(float(value))
        except ValueError:
            found.update(float(part) for part in re.findall(r"\d+", value))
    words = re.findall(r"[a-z]+", plain)
    for index, word in enumerate(words):
        if word in NUMBER_WORDS:
            found.add(float(NUMBER_WORDS[word]))
            # "treinta y dos" is also stated as 32.
            if (NUMBER_WORDS[word] in {30, 40, 50, 60, 70, 80, 90} and index + 2 < len(words)
                    and words[index + 1] == "y" and words[index + 2] in NUMBER_WORDS
                    and NUMBER_WORDS[words[index + 2]] < 10):
                found.add(float(NUMBER_WORDS[word] + NUMBER_WORDS[words[index + 2]]))
    return found
