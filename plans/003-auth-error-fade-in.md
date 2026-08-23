# 003 — Auth error: fade-in en lugar de display toggle

- **Status**: TODO
- **Commit**: 82188f7
- **Severity**: LOW
- **Category**: Preventing a jarring change
- **Estimated scope**: 1 file (report_template.html), CSS + 2 líneas JS

## Problem

`templates/report_template.html:325` — El mensaje de error de contraseña incorrecta
aparece instantáneamente con `display:none → block`. No tiene ninguna transición,
lo que crea un flash abrupto que rompe la calma del auth gate (que sí tiene su
propia animación de entrada suave `auth-in`).

```html
<!-- actual -->
<p id="auth-error" class="auth-error" style="display:none;">
  Contraseña incorrecta, intenta de nuevo
</p>
```

```javascript
// actual (en el handler de error de auth, ~línea 535 aprox.)
document.getElementById('auth-error').style.display = 'block';
```

`display` no es animable — si se hace `transition: opacity` pero se alterna
`display`, la transición nunca corre.

## Target

Usar `visibility + opacity + translateY` en lugar de `display`, de modo que la
transición sí pueda ejecutarse. El elemento ocupa espacio siempre (no colapsa
layout al mostrarse), lo que evita el salto de altura del form.

```css
/* target — reemplazar .auth-error */
.auth-error {
  color: var(--bad);
  font-size: 0.82rem;
  margin-top: 10px;
  font-weight: 500;
  opacity: 0;
  transform: translateY(-4px);
  transition: opacity 200ms ease-out, transform 200ms ease-out;
  /* NO display:none — usar visibility/opacity */
}
.auth-error.visible {
  opacity: 1;
  transform: translateY(0);
}
@media (prefers-reduced-motion: reduce) {
  .auth-error { transition: none; }
}
```

```html
<!-- target: eliminar style="display:none;" -->
<p id="auth-error" class="auth-error">Contraseña incorrecta, intenta de nuevo</p>
```

```javascript
// target: en lugar de .style.display = 'block'
document.getElementById('auth-error').classList.add('visible');

// y al resetear (si el usuario vuelve a escribir):
document.getElementById('auth-error').classList.remove('visible');
```

## Repo conventions to follow

- Patrón: `.auth-box` usa `animation: auth-in 380ms var(--ease-out) both` (línea 243).
  Este fix usa `transition` en lugar de `animation` porque el error puede mostrarse
  y ocultarse múltiples veces — las transiciones son interruptibles, los keyframes no.
- Duración: 200ms, mismo orden de magnitud que los toasts pequeños (ver AUDIT.md: "Tooltips, small popovers: 125–200ms").
- `prefers-reduced-motion` ya manejado en línea 309–314; añadir `.auth-error` ahí.

## Steps

1. **CSS** — Reemplazar el bloque `.auth-error` existente (línea ~301–306) con el Target CSS arriba.

2. **HTML** — Eliminar `style="display:none;"` del `<p id="auth-error">` (línea 325).

3. **JS** — Buscar todos los lugares donde se hace `.style.display = 'block'` o `.style.display = 'none'`
   sobre `auth-error` (buscar: `auth-error`) y reemplazarlos:
   - Mostrar error: `classList.add('visible')`
   - Ocultar error: `classList.remove('visible')`

4. **CSS — reduced-motion** — Dentro del `@media (prefers-reduced-motion: reduce)` existente (línea ~309):
   ```css
   .auth-error { transition: none; }
   ```

## Boundaries

- NO cambiar el texto del mensaje de error.
- NO afectar el layout del `.auth-box` — el elemento debe seguir ocupando su espacio
  cuando está invisible (no usar `display:none` ni `height:0`).
- NO añadir JS adicional más allá del cambio de clase.

## Verification

- **Feel check**:
  - Ingresar una contraseña incorrecta. El mensaje de error debe deslizarse hacia abajo
    desde arriba con fade en ~200ms. No debe "aparecer de golpe".
  - Ingresar otra contraseña incorrecta inmediatamente. La transición debe reiniciarse
    suavemente (la clase ya está, pero el estado no cambia — es idempotente).
  - En DevTools Animations a 10%: confirmar `opacity` y `translateY` transicionan juntos.
  - Con `prefers-reduced-motion` activo: el mensaje aparece instantáneamente, sin flash
    de contenido (porque el elemento ya existía en el DOM, solo cambia visibilidad).
- **Done when**: contraseña incorrecta → error aparece con fade suave; el auth box no
  salta de tamaño al mostrarse el error.
