/**
 * A plain, short list of rows (antd 6.6 deprecates List, and its successor
 * Listy is a virtual list meant for long ones). Semantic <ul>/<li>.
 */
export interface ItemListProps<T> {
  items: readonly T[]
  render: (item: T, index: number) => React.ReactNode
  rowKey: (item: T, index: number) => string
  /** extra attributes per row, e.g. data-* for tests */
  rowProps?: (item: T, index: number) => React.LiHTMLAttributes<HTMLLIElement> & Record<`data-${string}`, string>
  'aria-label'?: string
  dense?: boolean
}

export function ItemList<T>({ items, render, rowKey, rowProps, dense, ...aria }: ItemListProps<T>) {
  const pad = dense ? '4px 0' : '10px 0'
  return (
    <ul aria-label={aria['aria-label']} style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {items.map((item, i) => (
        <li
          key={rowKey(item, i)}
          {...rowProps?.(item, i)}
          style={{ padding: pad, borderBottom: i < items.length - 1 ? '1px solid rgba(5, 5, 5, 0.06)' : undefined }}
        >
          {render(item, i)}
        </li>
      ))}
    </ul>
  )
}
