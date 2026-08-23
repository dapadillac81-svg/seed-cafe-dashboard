# Animation Plans — Seed Café Dashboard

| # | Plan | Severidad | Status | Depende de |
|---|------|-----------|--------|------------|
| 001 | [Chart cards scroll fade-in](001-chart-cards-scroll-fade-in.md) | MEDIUM | TODO | — |
| 002 | [Botón producción press feedback](002-produccion-button-press-feedback.md) | LOW | TODO | — |
| 003 | [Auth error fade-in](003-auth-error-fade-in.md) | LOW | TODO | — |

## Orden de ejecución recomendado

1. **002** — más simple (solo CSS + cambio de markup), riesgo cero
2. **003** — requiere cambio en CSS + HTML + JS, but scope acotado
3. **001** — el mayor impacto visual; conviene hacerlo último para validar que
   no interfiere con el IntersectionObserver de navegación (que también usa el mismo API)

## Dependencias

- 001 y el observer de `initDashboard` para navegación comparten `IntersectionObserver`.
  Usar instancias separadas (la de navegación ya existe; crear `cardObserver` aparte).
- Ningún plan depende de otro para ejecutarse.
