import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SKIP_ERROR_TOAST } from '../http/error.interceptor';
import { META_URL, MetaService } from './meta.service';
import { MetaOut } from './models';
import { metaOut } from './testing';

describe('MetaService', () => {
  let service: MetaService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(MetaService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  it('shares one request between callers and keeps the answer', () => {
    const received: MetaOut[] = [];
    service.load().subscribe((meta) => received.push(meta));
    service.load().subscribe((meta) => received.push(meta));

    const request = http.expectOne(META_URL);
    expect(request.request.context.get(SKIP_ERROR_TOAST)).toBe(true);
    request.flush(metaOut());

    service.load().subscribe((meta) => received.push(meta));
    http.expectNone(META_URL);
    expect(received).toEqual([metaOut(), metaOut(), metaOut()]);
  });

  it('asks again after a failure instead of replaying it', () => {
    let failed = false;
    service.load().subscribe({ error: () => (failed = true) });
    http.expectOne(META_URL).flush(null, { status: 503, statusText: 'Service Unavailable' });
    expect(failed).toBe(true);

    let received: MetaOut | null = null;
    service.load().subscribe((meta) => (received = meta));
    http.expectOne(META_URL).flush(metaOut());
    expect(received).toEqual(metaOut());
  });
});
