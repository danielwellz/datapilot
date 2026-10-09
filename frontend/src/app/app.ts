import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { ToastStack } from './core/toast/toast-stack';

@Component({
  selector: 'dp-root',
  imports: [RouterOutlet, ToastStack],
  templateUrl: './app.html',
})
export class App {}
