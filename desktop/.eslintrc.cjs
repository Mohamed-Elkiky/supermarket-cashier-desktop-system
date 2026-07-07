/* ESLint (classic config) for the Supermarket POS desktop client.
 * Kept on ESLint 8 so the .eslintrc.cjs format works out of the box. */
module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
  ],
  settings: {},
  ignorePatterns: [
    "dist/",
    "release/",
    "node_modules/",
    "build/",
    "*.tsbuildinfo",
    "vite.config.d.ts",
    "coverage/",
  ],
  rules: {
    // The renderer is fully typed; TS handles unused detection.
    "no-unused-vars": "off",
    "@typescript-eslint/no-unused-vars": [
      "error",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
    ],
    // Hardware/serial/ESC-POS code legitimately touches loosely-typed buffers.
    "@typescript-eslint/no-explicit-any": "off",
    "@typescript-eslint/explicit-module-boundary-types": "off",
    "no-empty": ["error", { allowEmptyCatch: true }],
  },
  overrides: [
    {
      // Electron main-process code is CommonJS.
      files: ["electron/**/*.js", "*.cjs", "*.js"],
      env: { node: true, browser: false },
      parserOptions: { sourceType: "script" },
      rules: {
        "@typescript-eslint/no-var-requires": "off",
        "@typescript-eslint/no-require-imports": "off",
      },
    },
    {
      // Test files (vitest globals).
      files: ["**/__tests__/**", "**/*.test.ts", "**/*.test.tsx"],
      env: { node: true, browser: true },
      rules: {
        "@typescript-eslint/no-non-null-assertion": "off",
      },
    },
  ],
};
