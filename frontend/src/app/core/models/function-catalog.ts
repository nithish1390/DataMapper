/** The built-in formula functions, by group, as offered in the Mapping Builder's Functions tab.
 * Also sent to the backend with a mapping-sheet import, so the AI picks from exactly these. */
export interface Fn {
  name: string;
  template: string;
  desc: string;
  /** Only available when the XSLT version is 2.0. */
  v2?: boolean;
}

export const FUNCTION_GROUPS: { group: string; fns: Fn[] }[] = [
  {
    group: 'Data manipulation — text', fns: [
      { name: 'concat', template: "concat(a, ' ', b)", desc: 'Joins strings: concat(FName, " ", LName)' },
      { name: 'substring', template: 'substring(s, 1, 3)', desc: 'Part of a string: 1-based start, length' },
      { name: 'substring-before', template: "substring-before(s, '-')", desc: 'Text before the first occurrence' },
      { name: 'substring-after', template: "substring-after(s, '-')", desc: 'Text after the first occurrence' },
      { name: 'string-length', template: 'string-length(s)', desc: 'Number of characters' },
      { name: 'normalize-space', template: 'normalize-space(s)', desc: 'Trims and collapses whitespace' },
      { name: 'upper-case', template: 'upper-case(s)', desc: 'UPPER CASE (XSLT 1.0: written as translate())' },
      { name: 'lower-case', template: 'lower-case(s)', desc: 'lower case (XSLT 1.0: written as translate())' },
      { name: 'translate', template: "translate(s, '-', '')", desc: 'Character-by-character replace / remove' },
      { name: 'contains', template: "contains(s, 'x')", desc: 'true if s contains x' },
      { name: 'starts-with', template: "starts-with(s, 'x')", desc: 'true if s starts with x' },
      { name: 'ends-with', template: "ends-with(s, 'x')", desc: 'true if s ends with x' },
      { name: 'string', template: 'string(x)', desc: 'Converts to text' },
      { name: 'replace', template: "replace(s, '[^0-9]', '')", desc: 'Regular-expression replace, $1 back-references', v2: true },
      { name: 'matches', template: "matches(s, '^[A-Z]{2}[0-9]{2}')", desc: 'true if s matches the regular expression', v2: true },
      { name: 'string-join', template: "string-join(Item/Nm, ', ')", desc: 'Joins all values of a repeating field', v2: true },
    ],
  },
  {
    group: 'Numbers & aggregation', fns: [
      { name: 'number', template: 'number(x)', desc: 'Converts to a number' },
      { name: 'format-number', template: "format-number(x, '#,##0.00')", desc: "Number -> text: '0.00', '#,##0.00', '000'" },
      { name: 'sum', template: 'sum(Item/Amount)', desc: 'Total of a repeating field' },
      { name: 'round', template: 'round(x)', desc: 'Nearest whole number' },
      { name: 'floor', template: 'floor(x)', desc: 'Round down' },
      { name: 'ceiling', template: 'ceiling(x)', desc: 'Round up' },
      { name: '+ - * div mod', template: 'a + b', desc: 'Arithmetic operators' },
      { name: 'abs', template: 'abs(x)', desc: 'Absolute value', v2: true },
      { name: 'min', template: 'min(Item/Amount)', desc: 'Smallest value of a repeating field', v2: true },
      { name: 'max', template: 'max(Item/Amount)', desc: 'Largest value of a repeating field', v2: true },
      { name: 'avg', template: 'avg(Item/Amount)', desc: 'Average of a repeating field', v2: true },
    ],
  },
  {
    group: 'Looping / iteration', fns: [
      { name: 'count', template: 'count(Item)', desc: 'How many elements: count(HomePhone) > 0' },
      { name: 'position', template: 'position()', desc: 'Index (1-based) of the current loop item' },
      { name: 'last', template: 'last()', desc: 'Number of items in the current loop' },
      { name: 'exists', template: 'exists(x)', desc: 'true if x is present and non-empty' },
      { name: '.  /  ..', template: '../', desc: 'Current item / parent of the current item' },
      { name: 'current-group', template: 'current-group()', desc: 'Items of the current For-Each-Group, e.g. sum(current-group()/Amt)', v2: true },
      { name: 'current-grouping-key', template: 'current-grouping-key()', desc: 'The key of the current For-Each-Group', v2: true },
    ],
  },
  {
    group: 'Conditions', fns: [
      { name: 'if', template: "if(cond, 'then', 'else')", desc: 'Inline condition (becomes xsl:choose)' },
      { name: 'when', template: "when(c1, v1, c2, v2, 'otherwise')", desc: 'Multi-branch value' },
      { name: 'and / or', template: 'a and b', desc: 'Combine conditions' },
      { name: 'not', template: 'not(x)', desc: 'Negation' },
      { name: '= != < <= > >=', template: "a = 'x'", desc: 'Comparisons' },
      { name: 'true / false', template: 'true()', desc: 'Boolean constants' },
      { name: 'boolean', template: 'boolean(x)', desc: 'Converts to true/false' },
    ],
  },
  {
    group: 'Date / time', fns: [
      { name: 'current-dateTime', template: 'current-dateTime()', desc: "Now, ISO-8601, the server's time zone (XSLT 1.0: EXSLT date:date-time)" },
      { name: 'current-dateTime(zone)', template: "current-dateTime('Asia/Singapore')",
        desc: 'Now in a time zone, e.g. 2026-10-03T14:45:15+08:00', v2: true },
      { name: 'current-date(zone)', template: "current-date('Asia/Singapore')", desc: 'Today in a time zone, e.g. 2026-10-03', v2: true },
      { name: 'format-dateTime', template: "format-dateTime(value, 'dd/MM/yyyy HH:mm:ss')",
        desc: "ISO date/dateTime -> any format. Java pattern (dd/MM/yyyy HH:mm, yyyyMMdd, dd-MMM-yy) or picture ([D01]/[M01]/[Y0001])", v2: true },
      { name: 'parse-dateTime', template: "parse-dateTime(value, 'dd/MM/yyyy HH:mm:ss')",
        desc: 'Text in a fixed-width pattern -> ISO dateTime (or date), e.g. 30/09/2026 -> 2026-09-30' },
    ],
  },
];

/** The catalogue for one XSLT version (2.0-only functions dropped for 1.0), flat. */
export function functionCatalog(xslt2: boolean): { group: string; name: string; template: string; desc: string }[] {
  return FUNCTION_GROUPS.flatMap((g) => g.fns.filter((f) => !f.v2 || xslt2)
    .map((f) => ({ group: g.group, name: f.name, template: f.template, desc: f.desc })));
}
