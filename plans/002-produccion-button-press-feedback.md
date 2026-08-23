# 002 — Botón "Plan de producción": press feedback

- **Status**: TODO
- **Commit**: 82188f7
- **Severity**: LOW
- **Category**: Feedback gap
- **Estimated scope**: 1 file (report_template.html), 1 bloque CSS

## Problem

`templates/report_template.html:340` — El botón "Plan de producción (mañana)" tiene
estilos inline sin `:active` ni `transition`. Al presionarlo en móvil no hay ninguna
respuesta táctil visual, creando inconsistencia con los botones de nav (← →) y el
botón de auth que sí tienen `scale(0.94/0.97)` en `:active`.

```html
<!-- actual -->
<a href="pronostico.html" style="display:inline-block; padding:8px 16px;
   background:var(--accent-light); color:#fff; border-radius:8px;
   text-decoration:none; font-size:0.85rem; font-weight:bold;">
  📋 Plan de producción (mañana)
</a>
```

Los estilos están inline, por lo que no se pueden sobreescribir fácilmente con CSS.

## Target

Mover los estilos a una clase CSS `.btn-produccion` y añadir `:active` + `transition`.

```html
<!-- target -->
<a href="pronostico.html" class="btn-produccion">
  📋 Plan de producción (mañana)
</a>
```

```css
/* target — añadir en la sección de estilos */
.btn-produccion {
  display: inline-block;
  padding: 8px 16px;
  background: var(--accent-light);
  color: #fff;
  border-radius: var(--radius-sm);
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 600;
  font-family: inherit;
  letter-spacing: -0.01em;
  transition: transform 120ms cubic-bezier(0.23, 1, 0.32, 1),
              background 150ms ease;
  -webkit-user-select: none;
  user-select: none;
}
.btn-produccion:active {
  transform: scale(0.96);
  transition: transform 80ms ease-out;
}
@media (hover: hover) and (pointer: fine) {
  .btn-produccion:hover { background: var(--accent); }
}
@media (prefers-reduced-motion: reduce) {
  .btn-produccion { transition: background 150ms ease; }
}
```

## Repo conventions to follow

- Patrón de referencia exacto: `.nav-bar a` (línea 99–121) — misma transición `120ms var(--ease-out)`,
  mismo `:active { transform: scale(0.94); transition: transform 80ms ease-out; }`,
  mismo guard `@media (hover: hover) and (pointer: fine)`.
- Usar `var(--radius-sm)` (10px) en lugar del `border-radius: 8px` inline hardcodeado.
- Usar `font-weight: 600` (no `bold`) para consistencia con el resto de botones.

## Steps

1. **CSS** — Añadir el bloque `.btn-produccion` + sus variantes de estado en la sección
   `<style>`, después del bloque `.nav-bar a.disabled` (línea ~126).

2. **HTML** — Reemplazar el `<a>` con estilos inline (línea 340) por:
   ```html
   <a href="pronostico.html" class="btn-produccion">📋 Plan de producción (mañana)</a>
   ```

## Boundaries

- NO modificar el href ni el texto del enlace.
- NO tocar el wrapper `<div style="text-align:center; margin-bottom:12px;">`.
- NO añadir JS.

## Verification

- **Feel check**:
  - En móvil (o DevTools touch mode): presionar el botón. Debe comprimirse visualmente
    (~scale 0.96) en el momento del toque y volver suavemente al soltar.
  - Comparar con los botones ← → de la nav bar: el feel debe ser idéntico (misma velocidad,
    misma profundidad de press, mismo rebote de vuelta).
  - En DevTools Animations a 10%: confirmar que el press dura ~80ms y la vuelta ~120ms.
  - Con `prefers-reduced-motion` activo: solo cambia background, sin transform.
- **Done when**: presionar el botón en móvil produce el mismo feedback táctil que los botones de nav.
