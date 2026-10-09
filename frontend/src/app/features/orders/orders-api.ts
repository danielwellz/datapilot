import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { OrderListQuery, OrderOut, OrderPageOut } from '../../core/api/models';
import { SKIP_ERROR_TOAST } from '../../core/http/error.interceptor';

export const ORDERS_URL = '/api/orders';

/** The orders pages show every failure in place, so these requests raise no toast. */
function pageReported(): HttpContext {
  return new HttpContext().set(SKIP_ERROR_TOAST, true);
}

/** HTTP access to the orders endpoints. */
@Injectable({ providedIn: 'root' })
export class OrdersApi {
  private readonly http = inject(HttpClient);

  list(query: OrderListQuery): Observable<OrderPageOut> {
    return this.http.get<OrderPageOut>(ORDERS_URL, {
      params: toHttpParams(query),
      context: pageReported(),
    });
  }

  get(id: number): Observable<OrderOut> {
    return this.http.get<OrderOut>(`${ORDERS_URL}/${String(id)}`, { context: pageReported() });
  }
}

/** Leaves absent fields out and repeats a key for each value of a list. */
export function toHttpParams(query: OrderListQuery): HttpParams {
  let params = new HttpParams();
  for (const [key, value] of Object.entries(query) as [string, unknown][]) {
    if (Array.isArray(value)) {
      for (const item of value as readonly string[]) {
        params = params.append(key, item);
      }
    } else if (typeof value === 'string' || typeof value === 'number') {
      params = params.set(key, value);
    }
  }
  return params;
}
