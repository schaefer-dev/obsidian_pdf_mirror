// pandoc template for Obsidian notes rendered to PDF via Typst.
// Variables: title, notepath, paper, mainfont, codefont, lang.

#let horizontalRule = line(length: 100%, stroke: 0.5pt + luma(200))

$if(highlighting-definitions)$
$highlighting-definitions$
$endif$

#let accent = rgb("#5b5bd6")

// Obsidian callouts: kind -> (colour, label used when no title is given)
#let callout-styles = (
  note: (rgb("#086ddd"), "Note"),
  abstract: (rgb("#00bfbc"), "Abstract"),
  summary: (rgb("#00bfbc"), "Summary"),
  tldr: (rgb("#00bfbc"), "TL;DR"),
  info: (rgb("#086ddd"), "Info"),
  todo: (rgb("#086ddd"), "Todo"),
  tip: (rgb("#00bfbc"), "Tip"),
  hint: (rgb("#00bfbc"), "Hint"),
  important: (rgb("#00bfbc"), "Important"),
  success: (rgb("#08b94e"), "Success"),
  check: (rgb("#08b94e"), "Check"),
  done: (rgb("#08b94e"), "Done"),
  question: (rgb("#ec7500"), "Question"),
  help: (rgb("#ec7500"), "Help"),
  faq: (rgb("#ec7500"), "FAQ"),
  warning: (rgb("#ec7500"), "Warning"),
  caution: (rgb("#ec7500"), "Caution"),
  attention: (rgb("#ec7500"), "Attention"),
  failure: (rgb("#e93147"), "Failure"),
  fail: (rgb("#e93147"), "Fail"),
  missing: (rgb("#e93147"), "Missing"),
  danger: (rgb("#e93147"), "Danger"),
  error: (rgb("#e93147"), "Error"),
  bug: (rgb("#e93147"), "Bug"),
  example: (rgb("#7852ee"), "Example"),
  quote: (rgb("#9e9e9e"), "Quote"),
  cite: (rgb("#9e9e9e"), "Cite"),
  embed: (rgb("#7c7c7c"), "Embedded note"),
  dataview: (rgb("#9e9e9e"), "Dataview query (not rendered)"),
)

#let callout(kind: "note", title: none, body) = {
  let (color, label) = callout-styles.at(kind, default: (rgb("#086ddd"), upper(kind.first()) + kind.slice(1)))
  block(
    width: 100%,
    fill: color.lighten(92%),
    stroke: (left: 3pt + color),
    radius: (right: 3pt),
    inset: (x: 10pt, y: 8pt),
    breakable: true,
  )[
    #block(below: 0.8em, text(weight: "bold", fill: color.darken(15%))[#if title == none { label } else { title }])
    #body
  ]
}

#let task(state) = {
  let checked = state != " "
  box(
    width: 0.8em, height: 0.8em, baseline: 0.1em, radius: 2pt,
    stroke: 0.7pt + if checked { accent } else { luma(130) },
    fill: if checked { accent } else { none },
    align(center + horizon, text(size: 0.65em, fill: white, weight: "bold")[#if state == "x" or state == "X" { "✓" } else if checked { state }]),
  )
  h(0.4em)
}

#set document(title: [$title$])
#set page(
  paper: "$if(paper)$$paper$$else$a4$endif$",
  margin: (x: 2cm, top: 2cm, bottom: 2.2cm),
  numbering: "1 / 1",
  number-align: right,
  footer: context {
    set text(size: 7.5pt, fill: luma(140))
    [$notepath$]
    h(1fr)
    counter(page).display("1 / 1", both: true)
  },
)
#set text(
  font: ("$if(mainfont)$$mainfont$$else$Helvetica Neue$endif$", "Apple Color Emoji"),
  size: 10.5pt,
  lang: "$if(lang)$$lang$$else$de$endif$",
)
#set par(justify: false, leading: 0.7em, spacing: 1.1em)
#show raw: set text(font: ("$if(codefont)$$codefont$$else$Menlo$endif$", "Apple Color Emoji"), size: 0.9em)
#show raw.where(block: false): box.with(fill: luma(240), inset: (x: 2pt), outset: (y: 2pt), radius: 2pt)
#show raw.where(block: true): block.with(fill: luma(245), inset: 8pt, radius: 4pt, width: 100%)
#show heading: set text(weight: "semibold")
#show heading: set block(above: 1.4em, below: 0.7em)
#show heading.where(level: 1): set text(size: 1.5em)
#show heading.where(level: 2): set text(size: 1.3em)
#show heading.where(level: 3): set text(size: 1.15em)
#show link: set text(fill: accent)
#show quote.where(block: true): it => block(
  stroke: (left: 2pt + luma(200)), inset: (left: 10pt, y: 4pt), width: 100%,
  text(fill: luma(70), it.body),
)
#set table(inset: 6pt, stroke: 0.5pt + luma(200))
#show table.cell.where(y: 0): set text(weight: "bold")
#show figure.where(kind: table): set block(breakable: true)
#show figure.where(kind: table): set align(left)

$if(showtitle)$
#block(below: 1.4em)[
  #text(size: 2em, weight: "bold")[$title$]
]
$endif$

$body$
