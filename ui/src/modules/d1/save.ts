/**
 * Hand a file's content to the browser to save under `filename` (a download).
 * Kept apart so the page's tests can stand in for the browser.
 */
export function saveFile(content: Blob, filename: string): void {
  const url = URL.createObjectURL(content)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
  // The browser has taken the content by now; let the address go a little later.
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
