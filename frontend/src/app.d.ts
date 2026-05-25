// Type declarations for non-TypeScript imports.
declare module "*.svelte" {
  import type { ComponentType } from "svelte";
  const component: ComponentType;
  export default component;
}

declare module "svelte-spa-router";
declare module "svelte-spa-router/wrap";
