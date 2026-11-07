// A module of the demo's own, imported by a relative path.

export function markLine(mark) {
  return `#${mark.blunder_id} ${mark.played_san}: ${mark.note}`;
}
