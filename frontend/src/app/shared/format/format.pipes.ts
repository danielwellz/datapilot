import { Pipe, PipeTransform } from '@angular/core';

import { formatRelative, formatUtcDate, formatUtcDateTime } from './format';

@Pipe({ name: 'utcDateTime' })
export class UtcDateTimePipe implements PipeTransform {
  transform(iso: string): string {
    return formatUtcDateTime(iso);
  }
}

@Pipe({ name: 'utcDate' })
export class UtcDatePipe implements PipeTransform {
  transform(isoOrDay: string): string {
    return formatUtcDate(isoOrDay);
  }
}

/** Pure: pass the moment to measure from, so the text changes only when that does. */
@Pipe({ name: 'relativeTime' })
export class RelativeTimePipe implements PipeTransform {
  transform(iso: string, now: Date): string {
    return formatRelative(iso, now);
  }
}
