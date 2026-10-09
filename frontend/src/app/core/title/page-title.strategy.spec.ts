import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Title } from '@angular/platform-browser';
import { TitleStrategy, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { PageTitleStrategy } from './page-title.strategy';

@Component({ template: '' })
class Blank {}

describe('PageTitleStrategy', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([
          { path: 'orders', title: 'Orders', component: Blank },
          { path: 'untitled', component: Blank },
        ]),
        { provide: TitleStrategy, useClass: PageTitleStrategy },
      ],
    });
  });

  it('puts the page name before the product name', async () => {
    await (await RouterTestingHarness.create()).navigateByUrl('/orders');

    expect(TestBed.inject(Title).getTitle()).toBe('Orders – DataPilot');
  });

  it('uses the product name alone for a page without a title', async () => {
    await (await RouterTestingHarness.create()).navigateByUrl('/untitled');

    expect(TestBed.inject(Title).getTitle()).toBe('DataPilot');
  });
});
