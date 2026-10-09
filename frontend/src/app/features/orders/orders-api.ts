import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { OrderListQuery, OrderOut, OrderPageOut } from '../../core/api/models';
import { toHttpParams } from '../../core/api/query-params';
import { SKIP_ERROR_TOAST } from '../../core/http/error.interceptor';

export const ORDERS_URL = '/api/orders';

/** The orders pages show every failure in place, so these requests raise no toast. */
function withoutToast(): HttpContext {
  return new HttpContext().set(SKIP_ERROR_TOAST, true);
}

/** HTTP access to the orders endpoints. */
@Injectable({ providedIn: 'root' })
export class OrdersApi {
  private readonly http = inject(HttpClient);

  list(query: OrderListQuery): Observable<OrderPageOut> {
    return this.http.get<OrderPageOut>(ORDERS_URL, {
      params: toHttpParams(query),
      context: withoutToast(),
    });
  }

  get(id: number): Observable<OrderOut> {
    return this.http.get<OrderOut>(`${ORDERS_URL}/${String(id)}`, { context: withoutToast() });
  }
}
