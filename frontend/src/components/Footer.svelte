<script lang="ts">
  import { config } from "../lib/config";
</script>

<footer class="container py-4 text-center text-muted small">
  <div>
    <a class="text-muted" href="{config.API_BASE}/api"
      ><i class="fa-solid fa-code me-1"></i>OpenAPI</a
    >
    &middot;
    <a class="text-muted" href="https://www.apache.org/">The ASF</a>
    &middot;
    <span>{config.PRODUCT_NAME} - Questions should be sent to: users@infra.apache.org</span>
  </div>
</footer>
