import { describe, it, expect, beforeEach } from 'vitest'
import { useProjectStore } from '../../stores/project-store'

describe('project-store', () => {
  beforeEach(() => {
    useProjectStore.setState({ projects: [], activeProject: null })
  })

  it('starts with empty projects and no active project', () => {
    const state = useProjectStore.getState()
    expect(state.projects).toEqual([])
    expect(state.activeProject).toBeNull()
  })

  it('sets projects', () => {
    useProjectStore.getState().setProjects([
      { name: 'test', path: '/tmp/test', created_at: null, description: 'A test', n_references: 0, n_outputs: 3 },
    ])
    expect(useProjectStore.getState().projects).toHaveLength(1)
    expect(useProjectStore.getState().projects[0].name).toBe('test')
  })

  it('sets active project', () => {
    useProjectStore.getState().setActiveProject('my-project')
    expect(useProjectStore.getState().activeProject).toBe('my-project')
  })

  it('clears active project', () => {
    useProjectStore.getState().setActiveProject('my-project')
    useProjectStore.getState().setActiveProject(null)
    expect(useProjectStore.getState().activeProject).toBeNull()
  })
})
