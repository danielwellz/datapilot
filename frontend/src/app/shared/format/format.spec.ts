import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ChangeIndicator } from './change';
import {
  countryName,
  formatChange,
  formatCompactMoney,
  formatCount,
  formatDayRange,
  formatMoney,
  formatMonth,
  formatPercent,
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

  describe('numbers', () => {
    it('groups counts and writes a true minus sign', () => {
      expect(formatCount(69_500)).toBe('69,500');
      expect(formatCount(-3)).toBe('−3');
    });

    it.each([
      [7_512_345.67, '$7.5M'],
      [12_345, '$12.3K'],
      [950, '$950'],
      [1_000_000, '$1M'],
      [0, '$0'],
      [-2_500_000, '−$2.5M'],
    ])('abbreviates %d on an axis as "%s"', (amount, expected) => {
      expect(formatCompactMoney(amount)).toBe(expected);
    });

    it('writes fractions as percentages with the requested decimals', () => {
      expect(formatPercent(0.1234)).toBe('12.3%');
      expect(formatPercent(0.4567, 0)).toBe('46%');
      expect(formatPercent(1)).toBe('100.0%');
      expect(formatPercent(0)).toBe('0.0%');
      expect(formatPercent(-0.05)).toBe('−5.0%');
    });
  });

  describe('changes', () => {
    it('signs a rise and colors it favorable when up is good', () => {
      expect(formatChange(0.0732)).toEqual({
        text: '+7.3%',
        direction: 'up',
        sentiment: 'favorable',
      });
    });

    it('writes a fall with a true minus sign and colors it unfavorable when up is good', () => {
      expect(formatChange(-0.0071)).toEqual({
        text: '−0.7%',
        direction: 'down',
        sentiment: 'unfavorable',
      });
    });

    it('treats a rise as unfavorable when down is good, as for the refund rate', () => {
      expect(formatChange(0.069, 'down')).toEqual({
        text: '+6.9%',
        direction: 'up',
        sentiment: 'unfavorable',
      });
      expect(formatChange(-0.2, 'down').sentiment).toBe('favorable');
    });

    it.each([0, 0.00004, -0.00004])(
      'writes %d as an unsigned, neutral 0.0%% because that is what it rounds to',
      (change) => {
        expect(formatChange(change)).toEqual({
          text: '0.0%',
          direction: 'flat',
          sentiment: 'neutral',
        });
      },
    );

    it('rounds a large change and keeps its sign', () => {
      expect(formatChange(1.23456).text).toBe('+123.5%');
    });
  });

  describe('months and periods', () => {
    it('names a month by its first day in UTC', () => {
      expect(formatMonth('2026-09-01')).toBe('Sep 2026');
      expect(formatMonth('2026-01-01')).toBe('Jan 2026');
    });

    it('writes a range of days with the year once when both share it', () => {
      expect(formatDayRange('2026-09-08', '2026-10-07')).toBe('Sep 8\u2009–\u2009Oct 7, 2026');
      expect(formatDayRange('2025-12-08', '2026-01-07')).toBe(
        'Dec 8, 2025\u2009–\u2009Jan 7, 2026',
      );
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

  describe('change indicator', () => {
    @Component({
      imports: [ChangeIndicator],
      template: `<dp-change id="refunds" [change]="0.069" good="down" />
        <dp-change id="revenue" [change]="0.0732" />
        <dp-change id="flat" [change]="0" />
        <dp-change id="none" [change]="null" />`,
    })
    class Host {}

    function render(): HTMLElement {
      const fixture = TestBed.createComponent(Host);
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    it('renders a rising refund rate as unfavorable, keeping the plus sign', () => {
      const refunds = render().querySelector('#refunds .change');
      expect(refunds?.classList).toContain('change--unfavorable');
      expect(refunds?.textContent.replace(/\s+/g, ' ').trim()).toBe('+6.9% (unfavorable)');
    });

    it('renders a rise in revenue as favorable', () => {
      expect(render().querySelector('#revenue .change')?.classList).toContain('change--favorable');
    });

    it('leaves an unchanged value uncolored and without a judgement', () => {
      const flat = render().querySelector('#flat .change');
      expect(flat?.classList).toContain('change--neutral');
      expect(flat?.textContent.trim()).toBe('0.0%');
    });

    it('says there is nothing to compare with when the change is null', () => {
      expect(render().querySelector('#none')?.textContent.trim()).toBe('No earlier data');
    });
  });
});
