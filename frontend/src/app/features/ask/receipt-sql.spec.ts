import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CLIPBOARD_WRITE, ReceiptSql } from './receipt-sql';

const SQL = "SELECT\n  channel,\n  count(*) AS orders\nFROM v_orders\nWHERE status = 'paid'";

@Component({
  imports: [ReceiptSql],
  template: `<dp-receipt-sql [sql]="sql()" [expandedByDefault]="expanded()" />`,
})
class Host {
  readonly sql = signal(SQL);
  readonly expanded = signal(false);
}

describe('ReceiptSql', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;
  let write: ReturnType<typeof vi.fn<(text: string) => Promise<void>>>;

  async function render(expanded = false): Promise<void> {
    write = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    TestBed.configureTestingModule({ providers: [{ provide: CLIPBOARD_WRITE, useValue: write }] });
    fixture = TestBed.createComponent(Host);
    fixture.componentInstance.expanded.set(expanded);
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function toggle(): HTMLButtonElement {
    const button = element.querySelector<HTMLButtonElement>('.receipt-sql__toggle');
    if (button === null) {
      throw new Error('No toggle');
    }
    return button;
  }

  function code(): HTMLElement | null {
    return element.querySelector('.receipt-sql__code');
  }

  it('starts collapsed, saying how long the SQL is', async () => {
    await render();

    expect(toggle().getAttribute('aria-expanded')).toBe('false');
    expect(toggle().textContent.replace(/\s+/g, ' ').trim()).toBe('Show SQL that ran (5 lines)');
    expect(code()).toBeNull();
  });

  it('opens and closes the SQL', async () => {
    await render();

    toggle().click();
    await fixture.whenStable();
    expect(toggle().getAttribute('aria-expanded')).toBe('true');
    expect(toggle().getAttribute('aria-controls')).toBe(code()?.id);

    toggle().click();
    await fixture.whenStable();
    expect(code()).toBeNull();
  });

  it('can start open', async () => {
    await render(true);

    expect(code()).not.toBeNull();
  });

  it('numbers the lines and keeps the SQL text exact', async () => {
    await render(true);

    const lines = [...element.querySelectorAll('.receipt-sql__line')];
    expect(lines.map((line) => line.querySelector('.receipt-sql__number')?.textContent)).toEqual([
      '1',
      '2',
      '3',
      '4',
      '5',
    ]);
    const text = lines.map((line) =>
      [...line.querySelectorAll('[class^="sql-"]')].map((token) => token.textContent).join(''),
    );
    expect(text.join('\n')).toBe(SQL);
  });

  it('highlights keywords and strings as text, never as markup', async () => {
    await render(true);
    fixture.componentInstance.sql.set("SELECT '<b>bold</b>' AS x");
    await fixture.whenStable();

    expect(element.querySelector('.sql-keyword')?.textContent).toBe('SELECT');
    expect(element.querySelector('.sql-string')?.textContent).toBe("'<b>bold</b>'");
    expect(element.querySelector('b')).toBeNull();
  });

  it('says the SQL was copied', async () => {
    await render();

    element.querySelector<HTMLButtonElement>('.receipt-sql__copy')?.click();
    await fixture.whenStable();

    expect(write).toHaveBeenCalledWith(SQL);
    expect(element.querySelector('[role="status"]')?.textContent.trim()).toBe(
      'Copied to the clipboard.',
    );
  });

  it('says what to do when copying fails', async () => {
    await render();
    write.mockRejectedValue(new Error('denied'));

    element.querySelector<HTMLButtonElement>('.receipt-sql__copy')?.click();
    await fixture.whenStable();

    expect(element.querySelector('[role="status"]')?.textContent.trim()).toBe(
      'Copying failed. Open the SQL and select it instead.',
    );
  });
});

describe('CLIPBOARD_WRITE', () => {
  it('fails when the browser has no clipboard', async () => {
    const write = TestBed.inject(CLIPBOARD_WRITE);

    await expect(write('SELECT 1')).rejects.toThrow('The clipboard is not available.');
  });

  it("uses the browser's clipboard when there is one", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    try {
      await TestBed.inject(CLIPBOARD_WRITE)('SELECT 1');

      expect(writeText).toHaveBeenCalledWith('SELECT 1');
    } finally {
      Reflect.deleteProperty(navigator, 'clipboard');
    }
  });
});
