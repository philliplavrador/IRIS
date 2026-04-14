/**
 * Express routes for the IRIS memory tool surface.
 *
 * Phase 2 (REVAMP Task 2.4): thin proxy over the Python daemon's real
 * `/api/memory/events` and `/api/memory/sessions/*` endpoints. The legacy
 * L3 surface (`/memory/recall`, `/memory/propose_*`, `/memory/commit_*`,
 * etc.) was stubbed 503 in Phase 0 and is **not** proxied here anymore —
 * those endpoints come back online in Phases 3-10 as their server
 * modules land and the frontend re-adopts them.
 */
import type { Express, Request, Response } from "express";
import {
  daemonDelete,
  daemonGet,
  daemonPatch,
  daemonPost,
} from "../services/daemon-client.js";

function forwardError(res: Response, e: unknown): void {
  const msg = e instanceof Error ? e.message : String(e);
  // Best-effort: daemon-client throws with the status code baked into the
  // message. We don't parse that here — just report 502 with the message
  // so the frontend shows the daemon's explanation verbatim.
  res.status(502).json({ error: msg });
}

export function registerMemoryRoutes(app: Express): void {
  // -- events ----------------------------------------------------------
  app.get("/api/memory/events", async (req: Request, res: Response) => {
    try {
      const qs = new URLSearchParams(
        req.query as Record<string, string>,
      ).toString();
      const path = `/api/memory/events${qs ? `?${qs}` : ""}`;
      res.json(await daemonGet(path));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get(
    "/api/memory/events/:eventId",
    async (req: Request, res: Response) => {
      try {
        const eventId = String(req.params.eventId);
        res.json(
          await daemonGet(`/api/memory/events/${encodeURIComponent(eventId)}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.post(
    "/api/memory/events/verify_chain",
    async (req: Request, res: Response) => {
      try {
        res.json(
          await daemonPost("/api/memory/events/verify_chain", req.body ?? {}),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  // -- sessions --------------------------------------------------------
  app.post(
    "/api/memory/sessions/start",
    async (req: Request, res: Response) => {
      try {
        res.json(
          await daemonPost("/api/memory/sessions/start", req.body ?? {}),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.post(
    "/api/memory/sessions/:sessionId/end",
    async (req: Request, res: Response) => {
      try {
        const sessionId = String(req.params.sessionId);
        res.json(
          await daemonPost(
            `/api/memory/sessions/${encodeURIComponent(sessionId)}/end`,
            req.body ?? {},
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.get(
    "/api/memory/sessions/:sessionId",
    async (req: Request, res: Response) => {
      try {
        const sessionId = String(req.params.sessionId);
        res.json(
          await daemonGet(
            `/api/memory/sessions/${encodeURIComponent(sessionId)}`,
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  // -- messages --------------------------------------------------------
  app.post("/api/memory/messages", async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost("/api/memory/messages", req.body ?? {}));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get("/api/memory/messages", async (req: Request, res: Response) => {
    try {
      const qs = new URLSearchParams(
        req.query as Record<string, string>,
      ).toString();
      res.json(await daemonGet(`/api/memory/messages${qs ? `?${qs}` : ""}`));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get(
    "/api/memory/messages/search",
    async (req: Request, res: Response) => {
      try {
        const qs = new URLSearchParams(
          req.query as Record<string, string>,
        ).toString();
        res.json(
          await daemonGet(`/api/memory/messages/search${qs ? `?${qs}` : ""}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  // -- tool_calls ------------------------------------------------------
  app.post("/api/memory/tool_calls", async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost("/api/memory/tool_calls", req.body ?? {}));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.patch(
    "/api/memory/tool_calls/:toolCallId/output_artifact",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.toolCallId);
        res.json(
          await daemonPatch(
            `/api/memory/tool_calls/${encodeURIComponent(id)}/output_artifact`,
            req.body ?? {},
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  // -- runs ------------------------------------------------------------
  app.post("/api/memory/runs/start", async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost("/api/memory/runs/start", req.body ?? {}));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.post(
    "/api/memory/runs/:runId/complete",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.runId);
        res.json(
          await daemonPost(
            `/api/memory/runs/${encodeURIComponent(id)}/complete`,
            req.body ?? {},
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.post(
    "/api/memory/runs/:runId/fail",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.runId);
        res.json(
          await daemonPost(
            `/api/memory/runs/${encodeURIComponent(id)}/fail`,
            req.body ?? {},
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.get("/api/memory/runs", async (req: Request, res: Response) => {
    try {
      const qs = new URLSearchParams(
        req.query as Record<string, string>,
      ).toString();
      res.json(await daemonGet(`/api/memory/runs${qs ? `?${qs}` : ""}`));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get(
    "/api/memory/runs/:runId/lineage",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.runId);
        res.json(
          await daemonGet(`/api/memory/runs/${encodeURIComponent(id)}/lineage`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  // -- memory entries --------------------------------------------------
  app.post("/api/memory/entries", async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost("/api/memory/entries", req.body ?? {}));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.post(
    "/api/memory/entries/commit",
    async (req: Request, res: Response) => {
      try {
        res.json(
          await daemonPost("/api/memory/entries/commit", req.body ?? {}),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.post(
    "/api/memory/entries/discard",
    async (req: Request, res: Response) => {
      try {
        res.json(
          await daemonPost("/api/memory/entries/discard", req.body ?? {}),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.post(
    "/api/memory/entries/supersede",
    async (req: Request, res: Response) => {
      try {
        res.json(
          await daemonPost("/api/memory/entries/supersede", req.body ?? {}),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.get("/api/memory/entries", async (req: Request, res: Response) => {
    try {
      const qs = new URLSearchParams(
        req.query as Record<string, string>,
      ).toString();
      res.json(await daemonGet(`/api/memory/entries${qs ? `?${qs}` : ""}`));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get(
    "/api/memory/entries/:memoryId",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.memoryId);
        res.json(
          await daemonGet(`/api/memory/entries/${encodeURIComponent(id)}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.patch(
    "/api/memory/entries/:memoryId/status",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.memoryId);
        res.json(
          await daemonPatch(
            `/api/memory/entries/${encodeURIComponent(id)}/status`,
            req.body ?? {},
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.delete(
    "/api/memory/entries/:memoryId",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.memoryId);
        res.json(
          await daemonDelete(`/api/memory/entries/${encodeURIComponent(id)}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  // -- operations ------------------------------------------------------
  app.post("/api/memory/operations", async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost("/api/memory/operations", req.body ?? {}));
    } catch (e) {
      forwardError(res, e);
    }
  });

  // `search` before `:opId` so Express's registered-order match doesn't
  // route `/operations/search` into the single-op fetch handler.
  app.get(
    "/api/memory/operations/search",
    async (req: Request, res: Response) => {
      try {
        const qs = new URLSearchParams(
          req.query as Record<string, string>,
        ).toString();
        res.json(
          await daemonGet(`/api/memory/operations/search${qs ? `?${qs}` : ""}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.get("/api/memory/operations", async (req: Request, res: Response) => {
    try {
      const qs = new URLSearchParams(
        req.query as Record<string, string>,
      ).toString();
      res.json(await daemonGet(`/api/memory/operations${qs ? `?${qs}` : ""}`));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get(
    "/api/memory/operations/:opId",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.opId);
        res.json(
          await daemonGet(`/api/memory/operations/${encodeURIComponent(id)}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.post(
    "/api/memory/operations/:opId/executions",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.opId);
        res.json(
          await daemonPost(
            `/api/memory/operations/${encodeURIComponent(id)}/executions`,
            req.body ?? {},
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  // -- extraction ------------------------------------------------------
  app.post("/api/memory/extract", async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost("/api/memory/extract", req.body ?? {}));
    } catch (e) {
      forwardError(res, e);
    }
  });

  // -- artifacts -------------------------------------------------------
  app.post("/api/memory/artifacts", async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost("/api/memory/artifacts", req.body ?? {}));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get("/api/memory/artifacts", async (req: Request, res: Response) => {
    try {
      const qs = new URLSearchParams(
        req.query as Record<string, string>,
      ).toString();
      res.json(await daemonGet(`/api/memory/artifacts${qs ? `?${qs}` : ""}`));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get(
    "/api/memory/artifacts/:artifactId",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.artifactId);
        res.json(
          await daemonGet(`/api/memory/artifacts/${encodeURIComponent(id)}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.get(
    "/api/memory/artifacts/:artifactId/bytes",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.artifactId);
        const daemonUrl =
          process.env.IRIS_DAEMON_URL || "http://localhost:4002";
        const upstream = await fetch(
          `${daemonUrl}/api/memory/artifacts/${encodeURIComponent(id)}/bytes`,
        );
        if (!upstream.ok) {
          const text = await upstream.text();
          res.status(upstream.status === 404 ? 404 : 502).json({ error: text });
          return;
        }
        const contentType = upstream.headers.get("content-type");
        if (contentType) res.setHeader("Content-Type", contentType);
        const buf = Buffer.from(await upstream.arrayBuffer());
        res.send(buf);
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.delete(
    "/api/memory/artifacts/:artifactId",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.artifactId);
        res.json(
          await daemonDelete(`/api/memory/artifacts/${encodeURIComponent(id)}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  // -- datasets --------------------------------------------------------
  app.post("/api/memory/datasets", async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost("/api/memory/datasets", req.body ?? {}));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get("/api/memory/datasets", async (_req: Request, res: Response) => {
    try {
      res.json(await daemonGet("/api/memory/datasets"));
    } catch (e) {
      forwardError(res, e);
    }
  });

  app.get(
    "/api/memory/datasets/:datasetId",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.datasetId);
        res.json(
          await daemonGet(`/api/memory/datasets/${encodeURIComponent(id)}`),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.get(
    "/api/memory/datasets/:datasetId/versions",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.datasetId);
        res.json(
          await daemonGet(
            `/api/memory/datasets/${encodeURIComponent(id)}/versions`,
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.post(
    "/api/memory/datasets/:datasetId/profile",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.datasetId);
        res.json(
          await daemonPost(
            `/api/memory/datasets/${encodeURIComponent(id)}/profile`,
            req.body ?? {},
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );

  app.post(
    "/api/memory/datasets/:datasetId/derive",
    async (req: Request, res: Response) => {
      try {
        const id = String(req.params.datasetId);
        res.json(
          await daemonPost(
            `/api/memory/datasets/${encodeURIComponent(id)}/derive`,
            req.body ?? {},
          ),
        );
      } catch (e) {
        forwardError(res, e);
      }
    },
  );
}
