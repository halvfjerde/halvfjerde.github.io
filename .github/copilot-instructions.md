# Repo quick-start for AI coding agents

This is a small, static GitHub Pages site (no build system). Keep guidance concise and focused on the actual patterns and conventions in this repo.

## Big picture
- Static site served from root (GitHub Pages). Key pages:
  - `index.html` — main homepage with scroll-driven sections and inline JS/CSS
  - `portfolio.html` — portfolio page
  - `csv/index.html` — an in-browser CSV editor (larger single-file app)
- Styling is split between `stylesheet.css` and inline styles in pages (index and csv use their own local styles).
- Images and binary assets live under `images/` (icons, profile, metro_seoul PDFs).
- No package.json, bundler, or test runner present.

## How to run & preview locally
- No build step. Serve files locally using any static server, e.g.:

  ```bash
  # Python builtin server
  python3 -m http.server 8000

  # Or use VS Code Live Server / `npx serve` if preferred
  ```

- Open `http://localhost:8000` (or the port you choose) and test in a modern browser.
- Debugging: use browser DevTools (Console, Sources, Network, responsive mode, Lighthouse).

## Project-specific patterns & conventions (use these when editing)
- Scroll-driven hero (index):
  - Structure: `.scroll-container` -> `.sticky-wrapper` -> many `.content-layer` elements.
  - Behavior: inline script in `index.html` calculates progress as `scrollY / (container.offsetHeight - window.innerHeight)` and divides the timeline evenly across `steps.length`. When a given step is active, its `.content-layer` receives the `.active` class; past steps receive `.exit`.
  - When adding/removing steps: simply add/remove `.content-layer` elements in document order — the JS divides the timeline by `steps.length` so no code edit is required.

- Name slider (index): small text carousel using `#name-track` and `setInterval`. The transform is applied in `em` units; if you increase slides, adjust the translate offset logic accordingly.

- Project cards: `.project-grid` (2-column grid) and `.project-card`. Icons are kept in `images/icons/`. To add a project, follow the same HTML structure and add the icon file under `images/icons/`.

- Collapsible sections: pattern implemented in `top_script.js` and `bottom_script.js`.
  - Use `collbutton` class on the button and give the sibling element `inactive_content` to control expand/collapse.
  - The JS toggles `.inactive_content` and `style.maxHeight` for transitions.

- CSV editor (`csv/index.html`): a larger single-file app. It uses CSS variables (declared in `:root`) and many UI patterns (chips, menu lists, inline editing). Treat it as a self-contained module; it's not wired into any build or test harness.

## External integration points
- Pretendard font served from a CDN in `index.html`.
- CNAME file exists — repo is published to a custom domain via GitHub Pages. Deploy = push to the repo (no CI needed unless you add one).
- External links (Twitter/X, Instagram, GitHub, Discord) are present in `index.html`; be careful when refactoring these elements not to break the link layout or text-tracking code.

## Safe refactor guidance
- Prefer editing small, self-contained files. Example safe edits:
  - Add a `.content-layer` block (copy the structure used in `index.html` and keep its content compact).
  - Add a new project card — follow `.project-card` markup and put assets in `images/icons/`.
  - Update CSV UI only within `csv/` unless the change affects site-wide semantics.
- Avoid changing `CNAME` unless you control DNS for the custom domain.

## Examples (copy-ready snippets)
- Add a new content layer (index):

```html
<div class="content-layer" id="step-N">
  <h1>새 섹션 제목</h1>
  <p>간단한 설명을 여기에 넣습니다.</p>
</div>
```

- Add a project card:

```html
<a href="https://example.com" target="_blank" class="project-card">
  <img src="images/icons/myicon.png" alt="icon" class="project-icon">
  <div class="project-info">
    <span class="project-title">프로젝트 이름</span>
    <span class="project-desc">설명</span>
  </div>
</a>
```

- Collapsible block (use `collbutton`):

```html
<button class="collbutton">Toggle</button>
<div class="inactive_content">숨길/보일 컨텐츠</div>
```

## What to look for when making changes
- Index behavior is driven by DOM order, not hard-coded indexes — ensure order reflects visual flow.
- Animations rely on `transform` and `maxHeight` toggles; test on both desktop and mobile viewports after edits.
- Maintain use of `:root` CSS variables for colors and theme; prefer adding or reusing variables rather than hardcoding colors.
- Avoid adding heavy frameworks without a clear reason (this is intentionally minimal-solid vanilla HTML/CSS/JS).

---

If you'd like, I can also:
- Add a short `CONTRIBUTING.md` with the preview server command and testing checklist, or
- Expand this file with quick TODOs for accessibility checks (contrast, alt text) or localization notes.

Please review and tell me which sections are unclear or need more detail. ✅