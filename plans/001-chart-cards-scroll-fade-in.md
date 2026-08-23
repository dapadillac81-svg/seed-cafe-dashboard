# 001 — Chart cards: scroll-triggered fade-in con stagger

- **Status**: TODO
- **Commit**: 82188f7
- **Severity**: MEDIUM
- **Category**: Missed opportunity — preventing a jarring change
- **Estimated scope**: 1 file (report_template.html), ~30 líneas CSS + JS

## Problem

`templates/report_template.html:369–393` — Los `.chart-card` aparecen
instantáneamente al cargar la página y al hacer scroll. Las KPI cards ya tienen
entrada escalonada (`kpi-in`, delays 60–210ms) pero los gráficos debajo no tienen
ninguna transición, creando una inconsistencia visual. El usuario ve bloques blancos
aparecer abruptamente mientras hace scroll en el móvil.

```html
<!-- actual: sin ninguna animación de entrada -->
<div class="chart-card" data-chart-id="hourly">
  ...
</div>
```

```css
/* actual: sin opacity/transform inicial */
.chart-card {
  background: var(--card);
  border-radius: var(--radius-md);
  padding: 10px;
  margin-bottom: 16px;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border);
  overflow-x: auto;
}
```

## Target

Cada `.chart-card` entra con `opacity: 0 → 1` + `translateY(14px → 0)` al cruzar
el viewport, con 50ms de stagger entre cards consecutivas. La animación se dispara
**una sola vez** (unobserve después del primer trigger). Plotly ya habrá renderizado
para entonces (el scroll ocurre después de los ~800ms que tarda Plotly).

```css
/* target — añadir al bloque de .chart-card */
.chart-card {
  opacity: 0;
  transform: translateY(14px);
  /* transition controlada por JS después de observar */
}
.chart-card.visible {
  opacity: 1;
  transform: translateY(0);
  transition: opacity 400ms cubic-bezier(0.23, 1, 0.32, 1),
              transform 400ms cubic-bezier(0.23, 1, 0.32, 1);
}

@media (prefers-reduced-motion: reduce) {
  .chart-card { opacity: 1; transform: none; }
  .chart-card.visible { transition: none; }
}
```

```javascript
// target — añadir dentro de initDashboard(), después del bloque del observer de navegación
var cards = document.querySelectorAll('.chart-card');
if ('IntersectionObserver' in window) {
  var cardObserver = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry, idx) {
      if (entry.isIntersecting) {
        var card = entry.target;
        var delay = parseInt(card.getAttribute('data-stagger') || '0');
        setTimeout(function() {
          card.classList.add('visible');
        }, delay);
        cardObserver.unobserve(card);
      }
    });
  }, { threshold: 0.08 });

  cards.forEach(function(card, i) {
    card.setAttribute('data-stagger', String(i * 50));
    cardObserver.observe(card);
  });
} else {
  // Fallback: mostrar todo sin animación
  cards.forEach(function(c) { c.classList.add('visible'); });
}
```

## Repo conventions to follow

- El token de easing ya existe: `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)` (`:root`, línea 39).
  Usar el valor literal en CSS porque las transiciones dinámicas (clase `.visible`) necesitan
  el valor inline al momento en que se aplica la clase.
- Patrón de referencia: `.kpi-card` (línea 153–164) usa `animation: kpi-in 420ms var(--ease-out) both`
  con delays escalonados. Esta implementación sigue el mismo espíritu pero con IntersectionObserver
  en lugar de delays fijos (porque los cards están bajo el fold).
- `prefers-reduced-motion` ya manejado en línea 309–314; añadir `.chart-card` ahí mismo.

## Steps

1. **CSS — estado inicial de `.chart-card`** (línea ~185–193):
   Añadir `opacity: 0; transform: translateY(14px);` al bloque `.chart-card` existente.

2. **CSS — clase `.visible`** (después del bloque `.chart-card`):
   ```css
   .chart-card.visible {
     opacity: 1;
     transform: translateY(0);
     transition: opacity 400ms cubic-bezier(0.23, 1, 0.32, 1),
                 transform 400ms cubic-bezier(0.23, 1, 0.32, 1);
   }
   ```

3. **CSS — reduced-motion** (dentro del `@media (prefers-reduced-motion: reduce)` existente, línea ~309):
   ```css
   .chart-card        { opacity: 1; transform: none; }
   .chart-card.visible { transition: none; }
   ```

4. **JS — IntersectionObserver para cards** (dentro de `initDashboard()`, después del
   bloque que observa `.chart-card[data-chart-id]` para la navegación, línea ~440 aprox.):
   Insertar el bloque JS del Target arriba.

## Boundaries

- NO tocar el bloque `.kpi-card` — ya tiene su propia animación.
- NO añadir dependencias JS externas.
- NO modificar el markup HTML de los `.chart-card` (el `data-stagger` se asigna vía JS).
- NO cambiar el stagger por debajo de 40ms ni por encima de 80ms.
- Si el código en el commit difiere del citado aquí, STOP y reportar el drift.

## Verification

- **Mechanical**: abrir el archivo en el navegador localmente, verificar que no hay errores en consola.
- **Feel check**:
  - Cargar la página en móvil (o DevTools device mode). Los KPIs aparecen con stagger. Al hacer scroll hacia abajo, cada chart card aparece con fade+rise suave.
  - En DevTools → Animations panel, reducir velocidad a 25%. Confirmar que cada card entra con ~50ms de diferencia entre sí, de arriba hacia abajo.
  - Activar `prefers-reduced-motion` (DevTools → Rendering). Confirmar que las cards aparecen inmediatamente sin transición, sin flash de contenido invisible.
  - Recargar la página sin scroll: los primeros charts visibles en el viewport deben entrar inmediatamente al cruzar el threshold del observer.
- **Done when**: todas las `.chart-card` entran con fade+rise al primer scroll, la animación no repite al volver a pasar sobre ellas, y con reduced-motion todo es visible desde el inicio.
