import { CdkVirtualScrollViewport, ScrollingModule } from '@angular/cdk/scrolling';
import { Component, computed, input, signal, viewChild } from '@angular/core';

import { JsonValue, ResultColumnOut } from '../../core/api/models';
import { formatResult } from './result-cells';

/** Results longer than this scroll virtually; shorter ones render every row. */
export const VIRTUAL_SCROLL_THRESHOLD = 100;
/** Rows in view before the table scrolls inside the receipt. */
export const VISIBLE_ROWS = 12;
/** Matches `--row-height`; virtual scrolling needs it as a number. */
export const ROW_HEIGHT_PX = 32;

/**
 * The rows an answer returned. Up to {@link VIRTUAL_SCROLL_THRESHOLD} rows
 * render as a plain table; longer results (up to the 1,000-row limit) render
 * only the rows in view, with `aria-rowcount` and `aria-rowindex` so a screen
 * reader still knows the size of the table and where it is.
 */
@Component({
  selector: 'dp-result-table',
  imports: [ScrollingModule],
  templateUrl: './result-table.html',
  styleUrl: './result-table.scss',
})
export class ResultTable {
  readonly columns = input.required<readonly ResultColumnOut[]>();
  readonly rows = input.required<readonly (readonly JsonValue[])[]>();
  /** Names the table for assistive technology, for example after the question. */
  readonly label = input.required<string>();

  protected readonly result = computed(() => formatResult(this.columns(), this.rows()));
  protected readonly virtual = computed(() => this.rows().length > VIRTUAL_SCROLL_THRESHOLD);
  protected readonly itemSize = ROW_HEIGHT_PX;
  /** The header row plus the visible rows. */
  protected readonly viewportHeight = (VISIBLE_ROWS + 1) * ROW_HEIGHT_PX;

  private readonly viewport = viewChild(CdkVirtualScrollViewport);
  /**
   * The virtual viewport moves its rows with a transform, which carries a
   * sticky header along; moving the header back by the same distance keeps
   * it at the top.
   */
  protected readonly headerOffset = signal(0);

  protected syncHeader(): void {
    const viewport = this.viewport();
    if (viewport !== undefined) {
      this.headerOffset.set(-(viewport.getOffsetToRenderedContentStart() ?? 0));
    }
  }
}
