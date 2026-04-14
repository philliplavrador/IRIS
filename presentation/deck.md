# IRIS — presentation deck

Audience: the creator of SpikeLab. Working draft, built section by section.
Each slide has three blocks: **Visual** (image/SVG/HTML), **Words** (a couple words on the slide), **Script** (casual spoken script).

---

# Section 1 — Intro

## Slide 1 — Title

**Visual**

<div style="font-size: 6em; font-weight: 800; letter-spacing: 0.04em; color: #7dd3fc;">IRIS</div>

**Words**

a local AI research partner
*for data analysis*

**Script**

Hey — thanks for letting me show you this. So this is IRIS. It's a tool I've been building in the Kosik Lab and honestly using myself almost every day. Think of it as my research partner that lives on my laptop. I'm gonna keep this pretty casual and really I just want your reactions, since you've built SpikeLab and think about a lot of the same problems I do.

---

## Slide 2 — The goal

**Visual**

<div class="slide-icons">💬 → ⚙️ → 🧠</div>

**Words**

Chat. Run. Remember.

**Script**

The whole goal boils down to three things. One — you just chat with it in plain English, no scripts, no notebooks. Two — and this is the big one — it actually *runs* the analysis on your real data. Most AI tools just describe what you could do; IRIS does it. And three, it remembers. Decisions, findings, what the data looks like — all of that persists across sessions, so I never have to re-explain my project to the model. Oh, and it all runs locally. My data stays on my machine.

---

## Slide 3 — How it works

**Visual**

<svg class="diagram" viewBox="0 0 900 220" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#7dd3fc"/>
    </marker>
  </defs>
  <g font-family="system-ui, sans-serif" font-size="20" fill="#e2e8f0" text-anchor="middle">
    <rect x="30"  y="60" width="220" height="100" rx="14" fill="#1e293b" stroke="#7dd3fc" stroke-width="2"/>
    <text x="140" y="105">You</text>
    <text x="140" y="135" font-size="14" fill="#94a3b8">chat in the webapp</text>
    <rect x="340" y="60" width="220" height="100" rx="14" fill="#1e293b" stroke="#7dd3fc" stroke-width="2"/>
    <text x="450" y="105">Agent</text>
    <text x="450" y="135" font-size="14" fill="#94a3b8">Claude, local</text>
    <rect x="650" y="60" width="220" height="100" rx="14" fill="#1e293b" stroke="#7dd3fc" stroke-width="2"/>
    <text x="760" y="100">Your data</text>
    <text x="760" y="130" font-size="14" fill="#94a3b8">engine + workspace</text>
    <line x1="250" y1="110" x2="340" y2="110" stroke="#7dd3fc" stroke-width="2" marker-end="url(#arrow)"/>
    <line x1="560" y1="110" x2="650" y2="110" stroke="#7dd3fc" stroke-width="2" marker-end="url(#arrow)"/>
  </g>
</svg>

**Words**

You → Agent → Your data

**Script**

Quick mental model, super shallow. Left box is you, chatting in a webapp. Middle box is the agent — that's Claude, running through the Claude Code SDK. Right box is a local Python engine and a project folder that holds your data, plots, and memory. You say what you want, the agent turns that into a real pipeline and runs it against your data, and the results plus what we learned go back into the project. Next time I open this project, it all comes right back. That's the whole shape. I'm skipping what's *inside* the engine — the operations, the DSL, the memory layer — happy to go deep on any of that if you want, but let's see where your questions take us.

---

*(End of Section 1. Section 2 drafted next.)*
