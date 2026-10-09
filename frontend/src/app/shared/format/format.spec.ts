import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import {
  countryName,
  formatMoney,
  formatRelative,
  formatUtcDate,
  formatUtcDateTime,
  moneyParts,
} from './format';
import { RelativeTimePipe, UtcDatePipe, UtcDateTimePipe } from './format.pipes';
import { Money } from './money';

describe('formatting', () => {
  describe('money', () => {
    it('formats dollars with grouping and two decimals', () => {
      expect(formatMoney('1234.5')).toBe('$1,234.50');
      expect(formatMoney('0')).toBe('$0.00');
    });

    it('keeps every cent of amounts a double cannot hold exactly', () => {
      // Formatted as a Number, this amount comes out as $99,999,999,999,999.98.
      expect(formatMoney('99999999999999.99')).toBe('$99,999,999,999,999.99');
    });

    it('writes a negative amount with a true minus sign', () => {
      expect(formatMoney('-5')).toBe('−$5.00');
      expect(moneyParts('-1234.5')).toEqual({ sign: '−', unit: '$', figure: '1,234.50' });
    });
  });

  describe('dates', () => {
    it('shows times in UTC on a 24-hour clock', () => {
      expect(formatUtcDateTime('2026-03-01T23:30:00Z')).toBe('Mar 1, 2026, 23:30');
    });

    it('keeps the UTC day even when local time would be the next day', () => {
      expect(formatUtcDate('2026-03-01T23:59:59Z')).toBe('Mar 1, 2026');
      expect(formatUtcDate('2026-03-01')).toBe('Mar 1, 2026');
    });

    it.each([
      ['2026-10-08T11:59:30Z', 'just now'],
      ['2026-10-08T11:55:00Z', '5 minutes ago'],
      ['2026-10-08T09:00:00Z', '3 hours ago'],
      ['2026-10-07T10:00:00Z', 'yesterday'],
      ['2026-10-01T12:00:00Z', '7 days ago'],
      ['2026-07-01T12:00:00Z', '3 months ago'],
      ['2024-10-01T12:00:00Z', '2 years ago'],
      ['2026-10-08T12:00:05Z', 'just now'],
    ])('describes %s as "%s"', (iso, expected) => {
      expect(formatRelative(iso, new Date('2026-10-08T12:00:00Z'))).toBe(expected);
    });
  });

  describe('countries', () => {
    it('names a country by its code and keeps a code it does not know', () => {
      expect(countryName('DE')).toBe('Germany');
      expect(countryName('XX')).toBe('XX');
    });
  });

  describe('in templates', () => {
    @Component({
      imports: [Money, UtcDateTimePipe, UtcDatePipe, RelativeTimePipe],
      template: `<dp-money amount="-1234.5" /><span id="when">{{
          '2026-10-07T14:05:00Z' | utcDateTime
        }}</span
        ><span id="day">{{ '2026-10-07' | utcDate }}</span
        ><span id="ago">{{ '2026-10-07T12:00:00Z' | relativeTime: now }}</span>`,
    })
    class Host {
      readonly now = new Date('2026-10-08T12:00:00Z');
    }

    it('renders money with a quieter unit and the date pipes', () => {
      const fixture = TestBed.createComponent(Host);
      fixture.detectChanges();
      const element = fixture.nativeElement as HTMLElement;

      expect(element.querySelector('dp-money')?.textContent).toBe('−$1,234.50');
      expect(element.querySelector('.money__unit')?.textContent).toBe('$');
      expect(element.querySelector('#when')?.textContent).toBe('Oct 7, 2026, 14:05');
      expect(element.querySelector('#day')?.textContent).toBe('Oct 7, 2026');
      expect(element.querySelector('#ago')?.textContent).toBe('yesterday');
    });
  });
});
