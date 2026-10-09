import { readChartTokens } from './chart-tokens';

describe('readChartTokens', () => {
  it('resolves the palette, neutrals and font from custom properties', () => {
    const element = document.createElement('div');
    const values: Record<string, string> = {
      '--chart-1': '#2b3fbf',
      '--chart-2': '#99650a',
      '--chart-3': '#1c6f8c',
      '--chart-4': '#86398a',
      '--chart-5': '#525c6b',
      '--color-ink': '#121821',
      '--color-graphite': '#525c6b',
      '--color-rule': '#d3d9e1',
      '--color-sheet': '#ffffff',
      '--font-sans': "'IBM Plex Sans', sans-serif",
    };
    for (const [name, value] of Object.entries(values)) {
      element.style.setProperty(name, ` ${value} `);
    }
    document.body.append(element);

    expect(readChartTokens(element)).toEqual({
      palette: ['#2b3fbf', '#99650a', '#1c6f8c', '#86398a', '#525c6b'],
      ink: '#121821',
      graphite: '#525c6b',
      rule: '#d3d9e1',
      sheet: '#ffffff',
      fontFamily: "'IBM Plex Sans', sans-serif",
    });
    element.remove();
  });
});
