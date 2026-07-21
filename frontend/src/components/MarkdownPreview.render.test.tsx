import { render, screen } from '@testing-library/react'
import { describe, it } from 'vitest'
import { MarkdownPreview } from './MarkdownPreview'

describe('MarkdownPreview', () => {
  it('renders headings and emphasis', () => {
    render(<MarkdownPreview content={'# Title\n\n**Bold** and a list:\n\n- one\n- two'} />)
    screen.getByRole('heading', { name: 'Title' })
    screen.getByText('Bold')
    screen.getByText('one')
  })
})
