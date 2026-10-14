import js from '@eslint/js'
import { defineConfig, globalIgnores } from 'eslint/config'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

// House rule: the interface is never called a "wizard" in anything a user
// sees (HANDOFF §2). Catch it in string literals, templates and JSX text.
const noWizardWording = [
  'error',
  { selector: 'Literal[value=/wizard/i]', message: 'Never call the interface a "wizard" in user-facing text.' },
  { selector: 'TemplateElement[value.raw=/wizard/i]', message: 'Never call the interface a "wizard" in user-facing text.' },
  { selector: 'JSXText[value=/wizard/i]', message: 'Never call the interface a "wizard" in user-facing text.' },
]

export default defineConfig([
  globalIgnores(['dist', 'coverage', 'public/mockServiceWorker.js']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommendedTypeChecked,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      'no-restricted-syntax': noWizardWording,
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },
  {
    // Test and mock files export helpers next to components; fast refresh
    // does not apply to them.
    files: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/api/mocks/**'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
  {
    files: ['eslint.config.js'],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
])
