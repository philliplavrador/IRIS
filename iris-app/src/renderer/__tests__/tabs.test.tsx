import { describe, expect, it } from 'vitest'
import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs'

function Harness({ initial = 'one' }: { initial?: string }) {
  const [v, setV] = useState(initial)
  return (
    <Tabs value={v} onValueChange={setV}>
      <TabsList>
        <TabsTrigger value="one">One</TabsTrigger>
        <TabsTrigger value="two">Two</TabsTrigger>
        <TabsTrigger value="three">Three</TabsTrigger>
      </TabsList>
      <TabsContent value="one">Panel One</TabsContent>
      <TabsContent value="two">Panel Two</TabsContent>
      <TabsContent value="three">Panel Three</TabsContent>
    </Tabs>
  )
}

describe('Tabs a11y', () => {
  it('exposes tablist with three tabs, exactly one selected', () => {
    render(<Harness />)
    const tablist = screen.getByRole('tablist')
    expect(tablist).toBeInTheDocument()
    const tabs = within(tablist).getAllByRole('tab')
    expect(tabs).toHaveLength(3)
    const selected = tabs.filter((t) => t.getAttribute('aria-selected') === 'true')
    expect(selected).toHaveLength(1)
    expect(selected[0]).toHaveTextContent('One')
    expect(selected[0].getAttribute('data-state')).toBe('active')
  })

  it('wires aria-controls/labelledby between tabs and panels', () => {
    render(<Harness />)
    const tabOne = screen.getByRole('tab', { name: 'One' })
    expect(tabOne.id).toBe('tab-one')
    expect(tabOne.getAttribute('aria-controls')).toBe('panel-one')
    const panel = screen.getByRole('tabpanel')
    expect(panel.id).toBe('panel-one')
    expect(panel.getAttribute('aria-labelledby')).toBe('tab-one')
  })

  it('flips aria-selected and panel visibility on click', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('tab', { name: 'Two' }))
    expect(screen.getByRole('tab', { name: 'Two' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'One' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Panel Two')
  })

  it('supports arrow + Home/End keyboard navigation', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const one = screen.getByRole('tab', { name: 'One' })
    one.focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Two' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{End}')
    expect(screen.getByRole('tab', { name: 'Three' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{Home}')
    expect(screen.getByRole('tab', { name: 'One' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Three' })).toHaveAttribute('aria-selected', 'true')
  })
})
