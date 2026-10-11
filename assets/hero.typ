// README hero banner (1280×640 px). Rebuild with:
//   typst compile --format png --ppi 144 assets/hero.typ assets/hero.png

#let W = 640pt
#let H = 320pt
#set page(width: W, height: H, margin: 0pt, fill: none)
#set text(font: "Helvetica Neue", fill: white)

#let violet = rgb("#8b6cff")
#let lavender = rgb("#c9bcff")
#let muted = rgb("#a59fc4")
#let pdf-red = rgb("#e5484d")
#let mono(size: 6.5pt, fill: white, body) = text(font: "Menlo", size: size, fill: fill, body)

// ---------------------------------------------------------------- card + glow
#place(rect(
  width: W, height: H, radius: 20pt,
  fill: gradient.linear(rgb("#1c1930"), rgb("#2c2252"), angle: 25deg),
))
#place(dx: 300pt, dy: -120pt, circle(radius: 230pt, fill: gradient.radial(
  violet.transparentize(72%), violet.transparentize(100%),
)))

// ---------------------------------------------------------------- left: title
#let chip(label) = box(
  inset: (x: 7pt, y: 4.5pt), radius: 10pt,
  fill: white.transparentize(90%), stroke: 0.6pt + white.transparentize(75%),
  text(size: 7.5pt, fill: white.transparentize(10%), label),
)
#place(dx: 38pt, horizon, stack(
  mono(size: 8pt, fill: violet)[obsidian #sym.arrow.r pdf],
  v(14pt),
  par(leading: 0.32em, text(size: 33pt, weight: "bold", tracking: -0.5pt)[Obsidian\ PDF Mirror]),
  v(18pt),
  par(leading: 0.6em, text(size: 11.5pt, fill: lavender)[
    Your vault as a folder tree of PDFs, \ always in sync. Read and annotate \ on any e-ink tablet.
  ]),
  v(22pt),
  stack(dir: ltr, spacing: 5pt, chip[incremental], chip[deterministic], chip[hourly via launchd]),
))

// ---------------------------------------------------------------- vault tree
#let row(indent, icon, name, fill: white, active: false) = block(
  width: 100%, inset: (x: 5pt, y: 2.6pt), radius: 3pt,
  fill: if active { violet.transparentize(60%) } else { none },
  stack(dir: ltr, h(indent * 8pt), mono(fill: muted)[#icon], h(4pt), mono(fill: fill)[#name]),
)
#place(dx: 268pt, dy: 108pt, rect(
  width: 116pt, radius: 8pt, inset: 6pt,
  fill: rgb("#14121f").transparentize(10%), stroke: 0.7pt + rgb("#40386a"),
)[
  #stack(dir: ltr, spacing: 3pt, ..(rgb("#ff5f57"), rgb("#febc2e"), rgb("#28c840")).map(c => circle(radius: 2.2pt, fill: c)))
  #v(2pt)
  #set block(spacing: 1pt)
  #row(0, "▾", "My Vault", fill: lavender)
  #row(1, "▾", "Projects", fill: lavender)
  #row(2, "#", "Roadmap.md", active: true)
  #row(2, "#", "Ideas.md")
  #row(1, "▾", "Journal", fill: lavender)
  #row(2, "#", "2026-10-11.md")
  #row(1, "▸", "Reading", fill: lavender)
])

// ---------------------------------------------------------------- arrow
#place(dx: 390pt, dy: 156pt, block(width: 60pt, align(center, stack(
  mono(size: 5.6pt, fill: lavender)[pandoc \+ Typst],
  v(5pt),
  stack(dir: ltr,
    move(dy: 3.3pt, line(length: 48pt, stroke: (paint: violet, thickness: 1.4pt, cap: "round"))),
    polygon(fill: violet, (0pt, 0pt), (7pt, 4pt), (0pt, 8pt)),
  ),
))))

// ---------------------------------------------------------------- e-ink tablet
#let ink = rgb("#2b2b2b")
#let line-bar(w, fill: luma(185)) = rect(width: w, height: 2.4pt, radius: 1.2pt, fill: fill)
#let task(done, w) = stack(dir: ltr, spacing: 3pt,
  rect(width: 4.5pt, height: 4.5pt, radius: 1pt,
    stroke: 0.5pt + if done { ink } else { luma(140) }, fill: if done { ink } else { none }),
  move(dy: 1pt, line-bar(w)),
)
#let page-content = {
  set block(spacing: 4.2pt)
  text(size: 9pt, weight: "bold", fill: ink)[Roadmap]
  v(2pt)
  line-bar(100%)
  line-bar(88%)
  stack(dir: ltr, spacing: 3pt, line-bar(26pt), rect(width: 30pt, height: 4pt, radius: 1pt, fill: rgb("#f3e27a")), line-bar(30pt))
  v(3pt)
  rect(width: 100%, inset: (x: 5pt, y: 4.5pt), fill: luma(236), stroke: (left: 1.6pt + ink))[
    #set block(spacing: 3.5pt)
    #text(size: 5pt, weight: "bold", fill: ink)[Note]
    #line-bar(90%, fill: luma(170))
    #line-bar(64%, fill: luma(170))
  ]
  v(3pt)
  text(size: 6.5pt, weight: "bold", fill: ink)[Next steps]
  task(true, 62pt)
  task(true, 48pt)
  task(false, 70pt)
  v(3pt)
  line-bar(95%)
  line-bar(72%)
}

#place(dx: 470pt, dy: 62pt, rotate(3deg, origin: center, rect(
  width: 134pt, height: 184pt, radius: 9pt, inset: (x: 7pt, top: 7pt, bottom: 13pt),
  fill: rgb("#e9e7e1"), stroke: 0.8pt + rgb("#bcb8ae"),
)[
  #rect(width: 100%, height: 100%, radius: 2pt, fill: rgb("#f8f7f2"), stroke: 0.4pt + rgb("#d4d0c6"),
    inset: (x: 9pt, top: 10pt, bottom: 6pt))[
    #page-content
    #place(bottom + left, text(size: 3.6pt, fill: luma(150))[Projects/Roadmap.md])
    #place(bottom + right, text(size: 3.6pt, fill: luma(150))[1 / 2])
  ]
]))
// stylus
#place(dx: 613pt, dy: 100pt, rotate(6deg, stack(
  rect(width: 4.2pt, height: 148pt, radius: (top: 2pt), fill: gradient.linear(rgb("#3a3a40"), rgb("#55555c"))),
  polygon(fill: rgb("#2a2a2e"), (0pt, 0pt), (4.2pt, 0pt), (2.1pt, 9pt)),
)))
// PDF tag
#place(dx: 452pt, dy: 74pt, rotate(-8deg, box(
  inset: (x: 5pt, y: 3pt), radius: 3pt, fill: pdf-red,
  text(size: 7pt, weight: "bold", tracking: 0.6pt)[PDF],
)))
