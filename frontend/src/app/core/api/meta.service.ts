import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, shareReplay, throwError } from 'rxjs';

import { SKIP_ERROR_TOAST } from '../http/error.interceptor';
import { MetaOut } from './models';

export const META_URL = '/api/meta';

/**
 * The values the filter controls offer. They change only when the data is
 * reseeded, so the first answer is kept for the rest of the session and every
 * page that asks shares it.
 */
@Injectable({ providedIn: 'root' })
export class MetaService {
  private readonly http = inject(HttpClient);
  private cached: Observable<MetaOut> | null = null;

  /** Callers report failures themselves; a failure is not kept, so the next call tries again. */
  load(): Observable<MetaOut> {
    this.cached ??= this.http
      .get<MetaOut>(META_URL, { context: new HttpContext().set(SKIP_ERROR_TOAST, true) })
      .pipe(
        catchError((error: unknown) => {
          this.cached = null;
          return throwError(() => error);
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    return this.cached;
  }
}
