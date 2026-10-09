import { Component, computed, input, output, signal } from '@angular/core';

import { MetaOut, ProductRankOut, ProductRankingOut } from '../../core/api/models';
import { ChartView } from '../../shared/chart/chart';
import { ChartSpec, shortenLabel } from '../../shared/chart/chart-config';
import {
  formatCompactMoney,
  formatCount,
  formatMoney,
  formatPercent,
} from '../../shared/format/format';
import { Money } from '../../shared/format/money';
import { Panel, PanelView, RANKING_DAYS, TOP_PRODUCTS, panelView } from './dashboard.store';
import { PanelError } from './panel-error';
import { PanelSelect, SelectOption } from './panel-select';

const BAR_HEIGHT = 28;
const AXIS_HEIGHT = 40;

export function shareText(share: number | null): string {
  return share === null ? 'none' : formatPercent(share);
}

/** One bar per product, best first, with the exact figures in the tooltip. */
export function productChartSpec(items: readonly ProductRankOut[]): ChartSpec {
  return {
    kind: 'bar',
    horizontal: true,
    labels: items.map((item) => item.name),
    series: [{ label: 'Revenue', values: items.map((item) => Number(item.revenue)), color: 1 }],
    formatTick: formatCompactMoney,
    formatLabel: (label) => shortenLabel(label),
    tooltipLabel: (_series, index) => {
      const item = items.at(index);
      return item === undefined ? '' : `Revenue: ${formatMoney(item.revenue)}`;
    },
    tooltipFooter: (index) => {
      const item = items.at(index);
      return item === undefined
        ? []
        : [
            `Category: ${item.category}`,
            `Units sold: ${formatCount(item.units)}`,
            `Share of category: ${shareText(item.category_share)}`,
          ];
    },
  };
}

/** Products ranked by paid revenue, within one category or across all. */
@Component({
  selector: 'dp-product-ranking',
  imports: [ChartView, Money, PanelError, PanelSelect],
  templateUrl: './product-ranking.html',
  styleUrl: './product-ranking.scss',
})
export class ProductRanking {
  readonly panel = input.required<Panel<ProductRankingOut>>();
  readonly meta = input.required<Panel<MetaOut>>();
  readonly category = input.required<string | null>();
  readonly categoryChange = output<string | null>();

  protected readonly days = RANKING_DAYS;
  protected readonly top = TOP_PRODUCTS;
  protected readonly showTable = signal(false);
  protected readonly formatCount = formatCount;
  protected readonly shareText = shareText;

  protected readonly categories = computed<SelectOption[]>(() =>
    (this.meta().value()?.categories ?? []).map((name) => ({ value: name, label: name })),
  );

  protected readonly items = computed(() => this.panel().value()?.items ?? []);
  protected readonly spec = computed(() => productChartSpec(this.items()));
  /** Ties can return more than ten products, so the chart grows with its bars. */
  protected readonly chartHeight = computed(
    () => Math.max(this.items().length, 4) * BAR_HEIGHT + AXIS_HEIGHT,
  );

  protected readonly view = computed<PanelView>(() =>
    panelView(this.panel(), (value) => value.items.length === 0),
  );

  protected readonly caption = computed(() => {
    const category = this.category();
    return `The top ${String(this.top)} products${category === null ? '' : ` in ${category}`}, by paid revenue`;
  });

  protected readonly emptyText = computed(() => {
    const category = this.category();
    const products = category === null ? 'No product' : `No product in ${category}`;
    return `${products} sold in a paid order in the last ${String(this.days)} days.`;
  });
}
