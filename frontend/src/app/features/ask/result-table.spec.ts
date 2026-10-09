import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { JsonValue, ResultColumnOut } from '../../core/api/models';
import { ResultTable, VIRTUAL_SCROLL_THRESHOLD, VISIBLE_ROWS } from './result-table';

const COLUMNS: ResultColumnOut[] = [
  { name: 'country', type: 'string' },
  { name: 'revenue', type: 'number' },
];

@Component({
  imports: [ResultTable],
  template: `<dp-result-table
    [columns]="columns()"
    [rows]="rows()"
    label="Result of the question"
  />`,
})
class Host {
  readonly columns = signal<ResultColumnOut[]>(COLUMNS);
  readonly rows = signal<JsonValue[][]>([
    ['DE', '1234567.50'],
    ['GB', null],
  ]);
}

function manyRows(count: number): JsonValue[][] {
  return Array.from({ length: count }, (_, index) => [`C${String(index)}`, String(index)]);
}

describe('ResultTable', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;

  async function render(rows?: JsonValue[][]): Promise<void> {
    fixture = TestBed.createComponent(Host);
    if (rows !== undefined) {
      fixture.componentInstance.rows.set(rows);
    }
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function cells(): string[][] {
    return [...element.querySelectorAll('tbody tr')].map((row) =>
      [...row.querySelectorAll('td')].map((cell) => cell.textContent.trim()),
    );
  }

  it('shows every row of a short result, formatted by column type', async () => {
    await render();

    expect([...element.querySelectorAll('th')].map((cell) => cell.textContent.trim())).toEqual([
      'country',
      'revenue',
    ]);
    expect(cells()).toEqual([
      ['DE', '1,234,567.50'],
      ['GB', '—'],
    ]);
  });

  it('right-aligns number columns', async () => {
    await render();

    const header = [...element.querySelectorAll('th')];
    expect(header.map((cell) => cell.classList.contains('data-table__number'))).toEqual([
      false,
      true,
    ]);
    expect(element.querySelector('tbody td:last-child')?.classList).toContain('data-table__number');
  });

  it('labels a scrollable region that keyboard users can reach', async () => {
    await render();

    const region = element.querySelector('[role="region"]');
    expect(region?.getAttribute('aria-label')).toBe('Result of the question');
    expect(region?.getAttribute('tabindex')).toBe('0');
    expect((region as HTMLElement).style.maxHeight).toBe(`${String((VISIBLE_ROWS + 1) * 32)}px`);
  });

  it('keeps each column as wide as its widest value', async () => {
    await render();

    expect([...element.querySelectorAll('th')].map((cell) => cell.style.minWidth)).toEqual([
      '7ch',
      '12ch',
    ]);
  });

  it('says when the query returned no rows', async () => {
    await render([]);

    expect(element.textContent.trim()).toBe('The query ran and returned no rows.');
    expect(element.querySelector('table')).toBeNull();
  });

  it('renders a short result without virtual scrolling', async () => {
    await render(manyRows(VIRTUAL_SCROLL_THRESHOLD));

    expect(element.querySelector('cdk-virtual-scroll-viewport')).toBeNull();
    expect(element.querySelectorAll('tbody tr')).toHaveLength(VIRTUAL_SCROLL_THRESHOLD);
  });

  it('scrolls a long result virtually and tells assistive technology its size', async () => {
    await render(manyRows(VIRTUAL_SCROLL_THRESHOLD + 1));

    const viewport = element.querySelector<HTMLElement>('cdk-virtual-scroll-viewport');
    expect(viewport?.getAttribute('aria-label')).toBe('Result of the question');
    expect(viewport?.style.height).toBe(`${String((VISIBLE_ROWS + 1) * 32)}px`);
    expect(element.querySelector('table')?.getAttribute('aria-rowcount')).toBe('102');
    expect(element.querySelector('thead tr')?.getAttribute('aria-rowindex')).toBe('1');
    // jsdom has no layout, so the viewport renders no rows; the browser check covers them.
    expect(element.querySelectorAll('tbody tr').length).toBeLessThan(VIRTUAL_SCROLL_THRESHOLD);
  });
});
