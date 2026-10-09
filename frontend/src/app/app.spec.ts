import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';

describe('App', () => {
  it('renders the routed pages and the notifications region', async () => {
    TestBed.configureTestingModule({ imports: [App], providers: [provideRouter([])] });

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('router-outlet')).not.toBeNull();
    expect(element.querySelector('dp-toast-stack [aria-live]')).not.toBeNull();
  });
});
