import Workspace from '../../../../workspace';
export default async function Page({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <Workspace admin view="retrieval" runId={runId}/>;
}
