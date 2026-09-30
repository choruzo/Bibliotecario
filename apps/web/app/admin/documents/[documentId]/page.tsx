import Workspace from '../../../workspace';
export default async function Page({ params }: { params: Promise<{ documentId: string }> }) {
  const { documentId } = await params;
  return <Workspace admin view="documents" documentId={documentId}/>;
}
