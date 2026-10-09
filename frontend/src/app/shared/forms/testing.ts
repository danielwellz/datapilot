/** Helpers for page specs that drive forms through the DOM, as a user would. */
export function typeInto(root: HTMLElement, selector: string, value: string): void {
  const input = root.querySelector<HTMLInputElement>(selector);
  if (input === null) {
    throw new Error(`No input matches ${selector}`);
  }
  input.value = value;
  input.dispatchEvent(new Event('input'));
  input.dispatchEvent(new Event('blur'));
}

export function submitForm(root: HTMLElement): void {
  const form = root.querySelector('form');
  if (form === null) {
    throw new Error('No form on the page');
  }
  form.dispatchEvent(new Event('submit'));
}

export function textOf(root: HTMLElement, selector: string): string | null {
  return root.querySelector(selector)?.textContent.trim() ?? null;
}
