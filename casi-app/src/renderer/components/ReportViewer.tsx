import { useEffect, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { FileText, Check, RotateCcw } from 'lucide-react'
import { useProjectStore } from '../stores/project-store'
import { useWorkspaceStore } from '../stores/workspace-store'
import { api } from '../lib/api'
import { Button } from './ui/button'
import { Badge } from './ui/badge'
import { Card, CardContent, CardFooter, CardHeader } from './ui/card'
import { ScrollArea } from './ui/scroll-area'
import type { ReportSection, SectionStatus } from '../types'

function stripComments(md: string): string {
  return md.replace(/<!--[\s\S]*?-->/g, '')
}

function isDefaultTemplate(md: string): boolean {
  const stripped = stripComments(md).replace(/[#\s]/g, '')
  return stripped.length < 80 && /^(Report)?Summary(KeyFigures)?Methods?References?$/i.test(stripped)
}

function parseReportSections(markdown: string): ReportSection[] {
  const cleaned = stripComments(markdown)
  const lines = cleaned.split('\n')
  const sections: ReportSection[] = []
  let currentHeading = ''
  let currentContent: string[] = []

  for (const line of lines) {
    const headingMatch = line.match(/^##\s+(.+)/)
    if (headingMatch) {
      if (currentHeading) {
        sections.push({
          id: slugify(currentHeading),
          heading: currentHeading,
          content: currentContent.join('\n').trim(),
          status: 'draft',
        })
      }
      currentHeading = headingMatch[1]
      currentContent = []
    } else if (currentHeading) {
      currentContent.push(line)
    }
  }

  if (currentHeading) {
    sections.push({
      id: slugify(currentHeading),
      heading: currentHeading,
      content: currentContent.join('\n').trim(),
      status: 'draft',
    })
  }

  return sections
}

function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

export function ReportViewer() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const reportContent = useWorkspaceStore((s) => s.reportContent)
  const setReportContent = useWorkspaceStore((s) => s.setReportContent)
  const reportSections = useWorkspaceStore((s) => s.reportSections)
  const setReportSections = useWorkspaceStore((s) => s.setReportSections)
  const updateSectionStatus = useWorkspaceStore((s) => s.updateSectionStatus)

  useEffect(() => {
    if (!activeProject) return
    api.reportContent(activeProject).then(setReportContent)
  }, [activeProject, setReportContent])

  const parsedSections = useMemo(() => parseReportSections(reportContent), [reportContent])

  useEffect(() => {
    if (parsedSections.length > 0) {
      // Merge with existing statuses
      const existing = new Map(reportSections.map((s) => [s.id, s.status]))
      setReportSections(parsedSections.map((s) => ({
        ...s,
        status: existing.get(s.id) ?? 'draft',
      })))
    }
  }, [parsedSections])

  if (!reportContent.trim() || isDefaultTemplate(reportContent)) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center px-8">
        <FileText className="h-12 w-12 mb-4 text-muted-foreground/30" />
        <p className="text-sm font-medium">Report</p>
        <p className="text-xs text-muted-foreground mt-1 max-w-xs">
          Your analysis report will appear here as you work with the agent.
        </p>
      </div>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="max-w-2xl mx-auto px-6 py-8">
        {/* Title from first H1 if exists */}
        {reportContent.match(/^#\s+(.+)/m) && (
          <h1 className="text-2xl font-bold mb-6 pb-3 border-b">
            {reportContent.match(/^#\s+(.+)/m)![1]}
          </h1>
        )}

        {reportSections.map((section) => (
          <Card key={section.id} className="mb-6">
            <CardHeader className="flex-row items-center justify-between pb-3">
              <h2 className="text-lg font-semibold">{section.heading}</h2>
              <StatusBadge status={section.status} />
            </CardHeader>
            {section.content && (
              <CardContent className="prose prose-sm dark:prose-invert max-w-none [&_pre]:bg-muted [&_pre]:rounded-lg [&_pre]:border [&_pre]:p-3 [&_code]:text-xs [&_a]:text-primary">
                <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                  {section.content}
                </ReactMarkdown>
              </CardContent>
            )}
            <CardFooter className="gap-2 pt-3">
              <Button
                size="sm"
                variant={section.status === 'approved' ? 'default' : 'outline'}
                onClick={() => updateSectionStatus(section.id, 'approved')}
              >
                <Check className="h-3.5 w-3.5 mr-1" /> Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => updateSectionStatus(section.id, 'needs-revision')}
              >
                <RotateCcw className="h-3.5 w-3.5 mr-1" /> Request Revision
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </ScrollArea>
  )
}

function StatusBadge({ status }: { status: SectionStatus }) {
  switch (status) {
    case 'approved':
      return <Badge variant="success">Approved</Badge>
    case 'needs-revision':
      return <Badge variant="warning">Needs Revision</Badge>
    default:
      return <Badge variant="outline">Draft</Badge>
  }
}
