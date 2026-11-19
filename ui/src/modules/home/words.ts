/** The first page's words (team-facing: nobody is addressed; American spelling). */

export const TITLE = 'Potency reports'

export const LEDE =
  "From a study's data files to a report in the NIEHS format. Each step is checked before it runs, every table can be followed back to the files it came from, and every written section shows how it was written."

export const BOOKSHELF = 'Each report as the NCBI Bookshelf would show it, with its Word document and its PDF.'

export const API_PAGE = 'What the software does at each step, in plain words: what it reads, what it writes, and where the code is.'

export const NOTEBOOK = 'The same steps run as code in the notebook notebooks/workflow_walkthrough.ipynb.'

export const GROUPS: { group: 'data' | 'computation' | 'document'; title: string }[] = [
  { group: 'data', title: 'The data' },
  { group: 'computation', title: 'The analysis' },
  { group: 'document', title: 'The report' },
]
