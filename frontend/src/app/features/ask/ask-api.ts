import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AskIn,
  AskOut,
  ExamplesOut,
  HistoryPageOut,
  HistoryQuery,
  ModelsOut,
} from '../../core/api/models';
import { toHttpParams } from '../../core/api/query-params';
import { SKIP_ERROR_TOAST } from '../../core/http/error.interceptor';

export const AI_URL = '/api/ai';

/** HTTP access to the Ask your data endpoints. */
@Injectable({ providedIn: 'root' })
export class AskApi {
  private readonly http = inject(HttpClient);

  models(): Observable<ModelsOut> {
    return this.http.get<ModelsOut>(`${AI_URL}/models`, { context: withoutToast() });
  }

  examples(): Observable<ExamplesOut> {
    return this.http.get<ExamplesOut>(`${AI_URL}/examples`, { context: withoutToast() });
  }

  ask(body: AskIn): Observable<AskOut> {
    return this.http.post<AskOut>(`${AI_URL}/ask`, body, { context: withoutToast() });
  }

  history(query: HistoryQuery): Observable<HistoryPageOut> {
    return this.http.get<HistoryPageOut>(`${AI_URL}/history`, {
      params: toHttpParams(query),
      context: withoutToast(),
    });
  }
}

/** The Ask page explains every failure on the receipt it belongs to, so no toast. */
function withoutToast(): HttpContext {
  return new HttpContext().set(SKIP_ERROR_TOAST, true);
}
