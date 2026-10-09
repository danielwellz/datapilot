import {
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import {
  AbstractControl,
  NonNullableFormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { catchError, debounceTime, map, merge, of, startWith, Subject, switchMap } from 'rxjs';

import { MetaService } from '../../core/api/meta.service';
import {
  MetaOut,
  ORDER_CHANNELS,
  ORDER_STATUSES,
  OrderChannel,
  OrderSort,
  OrderStatus,
} from '../../core/api/models';
import { countryName } from '../../shared/format/format';
import { visibleError } from '../../shared/forms/form-errors';
import { CHANNEL_LABELS, STATUS_LABELS } from './order-labels';
import {
  NO_FILTERS,
  OrderFilters,
  TOTAL_PATTERN,
  activeFilterCount,
  compareTotals,
  hasFilters,
  sameFilters,
} from './order-filters';

/** How long typing in a date or total field pauses before the list reloads. */
export const TYPING_DEBOUNCE_MS = 300;

/** The form's value: empty strings for filters that are not set. */
interface FilterFormValue {
  statuses: Record<OrderStatus, boolean>;
  country: string;
  channel: OrderChannel | '';
  dateFrom: string;
  dateTo: string;
  minTotal: string;
  maxTotal: string;
  sort: OrderSort;
}

type MetaState = { status: 'loading' } | { status: 'loaded'; meta: MetaOut } | { status: 'failed' };

const TOTAL_MESSAGE = { pattern: 'Enter an amount like 250 or 99.50.' };

function rangesValidator(group: AbstractControl): ValidationErrors | null {
  const { dateFrom, dateTo, minTotal, maxTotal } = (group as AbstractControl<FilterFormValue>)
    .value;
  const errors: ValidationErrors = {};
  if (dateFrom && dateTo && dateFrom > dateTo) {
    errors['dateRange'] = true;
  }
  if (
    minTotal &&
    maxTotal &&
    TOTAL_PATTERN.test(minTotal) &&
    TOTAL_PATTERN.test(maxTotal) &&
    compareTotals(minTotal, maxTotal) > 0
  ) {
    errors['totalRange'] = true;
  }
  return Object.keys(errors).length > 0 ? errors : null;
}

/**
 * The controls that narrow the orders list. It shows the filters it is given
 * and emits a complete, valid set when the user changes one; it never changes
 * the URL itself. Choices apply at once; dates and totals wait until typing
 * pauses, and only valid values are emitted.
 */
@Component({
  selector: 'dp-order-filter-bar',
  imports: [ReactiveFormsModule],
  templateUrl: './order-filter-bar.html',
  styleUrl: './order-filter-bar.scss',
})
export class OrderFilterBar {
  private readonly metaService = inject(MetaService);
  private readonly fb = inject(NonNullableFormBuilder);

  readonly filters = input.required<OrderFilters>();
  readonly filtersChange = output<OrderFilters>();

  protected readonly statuses = ORDER_STATUSES;
  protected readonly statusLabels = STATUS_LABELS;
  protected readonly channels = ORDER_CHANNELS;
  protected readonly channelLabels = CHANNEL_LABELS;

  protected readonly form = this.fb.group(
    {
      statuses: this.fb.group({ paid: false, refunded: false, cancelled: false }),
      country: '',
      channel: this.fb.control<OrderChannel | ''>(''),
      // A date input's value is always '' or a real day; the browser drops anything else.
      dateFrom: '',
      dateTo: '',
      minTotal: ['', Validators.pattern(TOTAL_PATTERN)],
      maxTotal: ['', Validators.pattern(TOTAL_PATTERN)],
      sort: this.fb.control<OrderSort>('created_at'),
    },
    { validators: rangesValidator },
  );

  private readonly metaRequests = new Subject<void>();
  protected readonly meta = toSignal(
    this.metaRequests.pipe(
      startWith(undefined),
      switchMap(() =>
        this.metaService.load().pipe(
          map((meta): MetaState => ({ status: 'loaded', meta })),
          catchError(() => of<MetaState>({ status: 'failed' })),
          startWith<MetaState>({ status: 'loading' }),
        ),
      ),
    ),
    { requireSync: true },
  );

  /** Countries by name, always including the one in the URL so the select never hides it. */
  protected readonly countries = computed(() => {
    const meta = this.meta();
    const codes = new Set(meta.status === 'loaded' ? meta.meta.countries : []);
    const current = this.filters().country;
    if (current !== null) {
      codes.add(current);
    }
    return [...codes]
      .map((code) => ({ code, name: countryName(code) }))
      .sort((a, b) => a.name.localeCompare(b.name));
  });

  protected readonly firstDay = computed(() => this.loadedMeta()?.first_order_date ?? null);
  protected readonly lastDay = computed(() => this.loadedMeta()?.last_order_date ?? null);
  protected readonly customerId = computed(() => this.filters().customerId);
  protected readonly filtered = computed(() => hasFilters(this.filters()));
  protected readonly activeCount = computed(() => activeFilterCount(this.filters()));
  /** On narrow screens the fields fold away behind a button, so the orders stay in view. */
  protected readonly expanded = signal(false);

  constructor() {
    // The URL may change from outside (Back, a shared link, "Clear filters"),
    // so the form follows the filters it is given. It is left alone when it
    // already shows them, so nothing typed since is overwritten.
    effect(() => {
      const filters = this.filters();
      untracked(() => {
        const shown = this.read();
        if (shown === null || !sameFilters(shown, filters)) {
          this.form.setValue(toFormValue(filters), { emitEvent: false });
        }
      });
    });

    const { statuses, country, channel, sort, dateFrom, dateTo, minTotal, maxTotal } =
      this.form.controls;
    merge(
      merge(statuses.valueChanges, country.valueChanges, channel.valueChanges, sort.valueChanges),
      merge(
        dateFrom.valueChanges,
        dateTo.valueChanges,
        minTotal.valueChanges,
        maxTotal.valueChanges,
      ).pipe(debounceTime(TYPING_DEBOUNCE_MS)),
    )
      .pipe(takeUntilDestroyed())
      .subscribe(() => {
        this.emitIfChanged();
      });
  }

  /** Enter applies what was typed without waiting for the pause. */
  protected apply(): void {
    this.form.markAllAsTouched();
    this.emitIfChanged();
  }

  protected toggle(): void {
    this.expanded.update((expanded) => !expanded);
  }

  protected clear(): void {
    this.filtersChange.emit({ ...NO_FILTERS, sort: this.filters().sort });
  }

  protected removeCustomer(): void {
    this.filtersChange.emit({ ...this.filters(), customerId: null });
  }

  protected retryMeta(): void {
    this.metaRequests.next();
  }

  protected errorFor(control: 'minTotal' | 'maxTotal'): string | null {
    return visibleError(this.form.controls[control], TOTAL_MESSAGE);
  }

  /** A range message, once the user has left one of its fields. */
  protected rangeError(range: 'date' | 'total'): string | null {
    const [from, to] =
      range === 'date'
        ? [this.form.controls.dateFrom, this.form.controls.dateTo]
        : [this.form.controls.minTotal, this.form.controls.maxTotal];
    if (!this.form.hasError(`${range}Range`) || !(from.touched || to.touched)) {
      return null;
    }
    return range === 'date'
      ? 'The start date must be on or before the end date.'
      : 'The minimum total must not be more than the maximum.';
  }

  private loadedMeta(): MetaOut | null {
    const meta = this.meta();
    return meta.status === 'loaded' ? meta.meta : null;
  }

  private emitIfChanged(): void {
    const filters = this.read();
    if (filters !== null && !sameFilters(filters, this.filters())) {
      this.filtersChange.emit(filters);
    }
  }

  /** The filters the form shows, or null while any field is invalid. */
  private read(): OrderFilters | null {
    if (this.form.invalid) {
      return null;
    }
    const value = this.form.getRawValue();
    return {
      statuses: ORDER_STATUSES.filter((status) => value.statuses[status]),
      country: value.country || null,
      channel: value.channel || null,
      // Kept from the URL: no control edits it, only the chip removes it.
      customerId: this.filters().customerId,
      dateFrom: value.dateFrom || null,
      dateTo: value.dateTo || null,
      minTotal: value.minTotal || null,
      maxTotal: value.maxTotal || null,
      sort: value.sort,
    };
  }
}

function toFormValue(filters: OrderFilters): FilterFormValue {
  const checked = (status: OrderStatus) => filters.statuses.includes(status);
  return {
    statuses: {
      paid: checked('paid'),
      refunded: checked('refunded'),
      cancelled: checked('cancelled'),
    },
    country: filters.country ?? '',
    channel: filters.channel ?? '',
    dateFrom: filters.dateFrom ?? '',
    dateTo: filters.dateTo ?? '',
    minTotal: filters.minTotal ?? '',
    maxTotal: filters.maxTotal ?? '',
    sort: filters.sort,
  };
}
