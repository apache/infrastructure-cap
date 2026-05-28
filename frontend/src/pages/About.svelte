<script lang="ts">
  import { link } from "svelte-spa-router";
  import { config } from "../lib/config";

  const REPO_URL = "https://github.com/apache/infrastructure-cap";
  const ATR_URL = "https://release-test.apache.org/";
  const CONTACT_LIST = "users@infra.apache.org";
</script>

<svelte:head>
  <title>CAP - About</title>
  <meta
    name="description"
    content="An introduction to the Contingent Approval Platform: what CAP does, how the protocol works, and how external services hook into it."
  />
</svelte:head>

<div class="about-page">
  <!-- ------------------------------------------------------------------ -->
  <!-- Proof-of-concept notice                                            -->
  <!-- ------------------------------------------------------------------ -->
  <div class="alert alert-warning d-flex align-items-start" role="alert">
    <i class="fa-solid fa-triangle-exclamation fa-lg me-3 mt-1"></i>
    <div>
      <h2 class="h5 alert-heading mb-1">This is a demo of a work in progress!</h2>
      <p class="mb-1">
        This site is a <strong>proof-of-concept deployment</strong>. It hosts
        a public demonstration of the Contingent Approval Platform (CAP)
        while the service is still under active development and testing.
      </p>
      <p class="mb-0 small">
        Features on thie site may be missing or incomplete,
        data may be reset without notice, schemas may change,
        and outcomes recorded here are not yet authoritative for any
        ASF project. Treat everything you see as illustrative until
        the service is formally in production.
      </p>
    </div>
  </div>

  <!-- ------------------------------------------------------------------ -->
  <!-- Heading + short intro                                              -->
  <!-- ------------------------------------------------------------------ -->
  <h1 class="h3 mt-4 mb-3">
    <i class="fa-solid fa-feather-pointed me-2 text-primary"></i>
    About the Contingent Approval Platform
  </h1>

  <section class="mb-4">
    <p>
      The <strong>Contingent Approval Platform</strong> (or CAP for short) is
      a foundation-wide service that captures and records the technical
      decisions taken by projects and services at the Apache Software Foundation (ASF).
      Wherever a project or service needs to ask a binary or graded question of a community
      (a release vote, a committee sign-off, a lazy consensus on a
      configuration change, an approval for a sensitive operation, etc.), CAP
      can provide a canonical place to file the question, gather the
      responses, and record the outcome with a permanent resolution link.
    </p>

    <p>
      CAP models every decision as a <em>question</em> with a fixed
      <em>response option</em> (a vote, a lazy consensus, or a free-text
      response), a <em>target audience</em>, a <em>scope</em> (the project
      the question is filed against, and optionally a privacy flag for
      committee-only questions), and a hard <em>closes_at</em> deadline.
      Every state-changing action against a question, from the initial
      filing through each individual response to the final resolution, is
      written to an append-only <strong>audit log</strong> inside the same
      database transaction as the action itself. The audit trail and MFA
      requirements of CAP lends better security assurances for project
      decisions.
    </p>

    <p>
      CAP distinguishes <strong>binding</strong> votes (votes from members
      of the project's management committee) from non-binding votes, and
      enforces that distinction at tally time. The tally rules vary by
      approval type: a unanimous-approval question is decided by whether
      any binding voter holds a veto, a majority-approval question by
      counting binding votes, and a lazy-consensus question by whether
      any objection (binding or not) has been raised in the window. The
      rules are fixed in code so that every project sees the same
      determinstic process, logic, and arithmetic.
    </p>

    <p>
      External services can <strong>outsource their decision-recording
      logic to CAP</strong>. Rather than reinventing voting plumbing
      inside every tool that needs a sign-off, a service files a question
      through CAP's HTTP API, subscribes to the pubsub event stream (or
      polls the resolution endpoint), and asynchronously proceeds once
      CAP reports the outcome. The Apache Trusted Release service (ATR),
      <code>.asf.yaml</code> automation, and other infrastructure tools
      are candidate consumers; see <a href="#external-services">External
      services</a> below.
    </p>

    <p>
      The long-term goal is a more <strong>uniform and user-friendly</strong>
      decision-making process across all Apache projects, and across most
      of the services they rely on: one user interface, one audit format,
      one event stream, and a single canonical permalink for every
      recorded outcome.
    </p>
  </section>

  <!-- ------------------------------------------------------------------ -->
  <!-- User workflow                                                      -->
  <!-- ------------------------------------------------------------------ -->
  <h2 id="user-workflow" class="h4 mt-5 mb-3">
    <i class="fa-solid fa-route me-2 text-primary"></i>
    The user workflow
  </h2>

  <p>
    The diagram below walks through the lifecycle of a question, from the
    moment a user logs in through to the publication of the resolution.
    The common flow is the same across all approval types; the three
    cards inside the resolution step show how the tally rules differ
    between <em>unanimous approval</em>, <em>majority approval</em>, and
    <em>lazy consensus</em>.
  </p>

  <div class="workflow-chart my-4" role="img"
       aria-label="Flow chart of the CAP question lifecycle">
    <!-- Step 1: log in -->
    <div class="wf-step">
      <div class="wf-step-icon"><i class="fa-solid fa-right-to-bracket"></i></div>
      <div class="wf-step-body">
        <div class="wf-step-title">1. Log in via ASF OAuth</div>
        <div class="wf-step-text">
          The user opens CAP and signs in with their Apache account. The
          session reveals which projects the user is a member of, and
          which of those projects they hold a committee (binding) seat
          on. Anyone may browse public questions; only logged-in users
          may file or respond.
        </div>
      </div>
    </div>

    <div class="wf-arrow" aria-hidden="true">
      <i class="fa-solid fa-arrow-down"></i>
    </div>

    <!-- Step 2: create question -->
    <div class="wf-step">
      <div class="wf-step-icon"><i class="fa-solid fa-circle-plus"></i></div>
      <div class="wf-step-body">
        <div class="wf-step-title">2. File a new question</div>
        <div class="wf-step-text">
          The requester picks a project they are a member of, writes the
          question (title, description, target audience), chooses an
          <strong>approval type</strong> (unanimous, majority, or lazy
          consensus) and a <strong>response option</strong> (vote, lazy
          consensus, or free text), and sets a <strong>closes_at</strong>
          deadline. Committee members may additionally mark a question
          <em>private</em>, scoping its event stream to the project's
          private list.
        </div>
      </div>
    </div>

    <div class="wf-arrow" aria-hidden="true">
      <i class="fa-solid fa-arrow-down"></i>
    </div>

    <!-- Step 3: publish -->
    <div class="wf-step">
      <div class="wf-step-icon"><i class="fa-solid fa-tower-broadcast"></i></div>
      <div class="wf-step-body">
        <div class="wf-step-title">3. Question is published</div>
        <div class="wf-step-text">
          CAP writes the question to its database, appends a
          <code>question.created</code> row to the audit log, sends an
          announcement to the project's mailing list (or the private
          list, for private questions), and broadcasts a structured
          event on the pubsub stream so external consumers can react.
        </div>
      </div>
    </div>

    <div class="wf-arrow" aria-hidden="true">
      <i class="fa-solid fa-arrow-down"></i>
    </div>

    <!-- Step 4: respond -->
    <div class="wf-step">
      <div class="wf-step-icon"><i class="fa-solid fa-comment-dots"></i></div>
      <div class="wf-step-body">
        <div class="wf-step-title">4. Audience members respond</div>
        <div class="wf-step-text">
          Voters in the target audience load the question and submit a
          response that matches the question's response option. Each
          response is timestamped, attributed, and stamped as either
          <strong>binding</strong> (voter is on the project's committee)
          or <strong>non-binding</strong>. Voters may amend their
          response at any time before resolution; the latest submission
          per voter is the one that counts, and the earlier rows are
          retained for the audit trail.
        </div>
      </div>
    </div>

    <div class="wf-arrow" aria-hidden="true">
      <i class="fa-solid fa-arrow-down"></i>
    </div>

    <!-- Step 5: resolution (with three-up tally cards) -->
    <div class="wf-step wf-step-resolve">
      <div class="wf-step-icon"><i class="fa-solid fa-gavel"></i></div>
      <div class="wf-step-body">
        <div class="wf-step-title">5. Resolution</div>
        <div class="wf-step-text">
          When the deadline elapses (or the requester explicitly calls
          resolve), CAP runs the tally for the question's approval
          type. The three cards below summarize the rules.
        </div>

        <div class="row g-3 mt-1">
          <div class="col-md-4">
            <div class="card h-100 border-primary-subtle">
              <div class="card-body">
                <h3 class="h6 mb-2">
                  <i class="fa-solid fa-balance-scale text-primary me-1"></i>
                  Unanimous approval
                </h3>
                <p class="small mb-0">
                  Passes if no <strong>binding</strong> voter holds a
                  <code>-1</code> veto at the deadline, <em>and</em> at
                  least <strong>three</strong> binding voters have cast
                  a <code>+1</code>. A veto requires a non-empty comment
                  and may be <em>withdrawn</em> by the same voter
                  submitting a non-veto response before resolution.
                  Non-binding <code>-1</code> votes are recorded but
                  cannot block approval; falling short of three binding
                  <code>+1</code> votes resolves the question as
                  <em>insufficient_votes</em>.
                </p>
              </div>
            </div>
          </div>
          <div class="col-md-4">
            <div class="card h-100 border-primary-subtle">
              <div class="card-body">
                <h3 class="h6 mb-2">
                  <i class="fa-solid fa-thumbs-up text-primary me-1"></i>
                  Majority approval
                </h3>
                <p class="small mb-0">
                  Passes if at least <strong>three</strong> binding
                  voters have cast a <code>+1</code> <em>and</em> the
                  binding <code>+1</code> tally strictly exceeds the
                  binding <code>-1</code> tally at the deadline.
                  Non-binding votes are recorded alongside but do not
                  decide the outcome. There are no vetoes: a
                  <code>-1</code> is just a counted vote against.
                </p>
              </div>
            </div>
          </div>
          <div class="col-md-4">
            <div class="card h-100 border-primary-subtle">
              <div class="card-body">
                <h3 class="h6 mb-2">
                  <i class="fa-solid fa-feather text-primary me-1"></i>
                  Lazy consensus
                </h3>
                <p class="small mb-0">
                  Silence is assent. The question is approved at the
                  deadline provided no objection (binding or non-binding)
                  was recorded during the voting window. Any objection,
                  from any audience member, blocks approval and marks
                  the question as <em>insufficient_votes</em>.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="wf-arrow" aria-hidden="true">
      <i class="fa-solid fa-arrow-down"></i>
    </div>

    <!-- Step 6: outcome + audit -->
    <div class="wf-step">
      <div class="wf-step-icon"><i class="fa-solid fa-stamp"></i></div>
      <div class="wf-step-body">
        <div class="wf-step-title">6. Outcome is recorded</div>
        <div class="wf-step-text">
          CAP writes the outcome (<code>approved</code>,
          <code>vetoed</code>, <code>insufficient_votes</code>, or
          <code>withdrawn</code>) to the audit log, issues a stable
          <strong>permalink</strong> for the resolution, posts a
          summary to the project list, and emits the final event on
          the pubsub stream. The question itself becomes read-only;
          its tally, every response, and every state change remain
          inspectable forever via the permalink.
        </div>
      </div>
    </div>
  </div>

  <p class="text-muted small">
    A withdrawn question follows a shortened path: the requester
    cancels the question before resolution, CAP records the
    <code>withdrawn</code> outcome, notifies the mailing list, and
    emits the final event. No tally is run.
  </p>

  <!-- ------------------------------------------------------------------ -->
  <!-- External services                                                  -->
  <!-- ------------------------------------------------------------------ -->
  <h2 id="external-services" class="h4 mt-5 mb-3">
    <i class="fa-solid fa-plug-circle-bolt me-2 text-primary"></i>
    Integrating external services
  </h2>

  <p>
    CAP is designed to act as a shared decision-recording backend for
    other Apache infrastructure. The HTTP API and the pubsub event
    stream together provide everything an automated workflow needs to
    file a question, wait for a verdict, and resume on the outcome,
    without having to host its own voting machinery.
  </p>

  <p>
    A typical integration looks like this:
  </p>

  <ol>
    <li>
      The external service decides it needs an approval (for example,
      ATR (<a href="{ATR_URL}" target="_blank" rel="noopener">{ATR_URL}</a>)
      detects that a release candidate is ready for a PMC vote, or a
      <code>.asf.yaml</code> workflow detects a change that requires a
      committee sign-off).
    </li>
    <li>
      It calls <code>POST /api/question</code> with the question body,
      using an ASF personal access token issued by
      <code>GET /api/token</code>. The question carries a
      <code>request_id</code> generated by the calling service so the
      service can correlate the future verdict back to its own state.
    </li>
    <li>
      The service either subscribes to the CAP pubsub topic for that
      project, or polls
      <code>GET /api/resolution/&#123;question_id&#125;</code> at a slow
      cadence. The pubsub path is preferred; it delivers the
      <code>question.resolved</code> event as soon as the tally has
      been recorded, so the service can react with no polling lag.
    </li>
    <li>
      On <code>question.resolved</code>, the service reads the outcome
      and the resolution permalink, then asynchronously proceeds with
      the original operation (publish the release, merge the change,
      apply the config, whichever it was waiting on). The permalink
      is included in any downstream notification so reviewers can
      trace the operation back to the decision that authorized it.
    </li>
  </ol>

  <p>
    Because CAP is the system of record for the decision, the calling
    service does not need to store the vote tally itself. It records
    only its own state (waiting on question X, proceeded after
    question X resolved as Y) and a link to the CAP permalink. This
    keeps the calling service simple and ensures every project sees
    the same vote semantics regardless of which tool initiated the
    question.
  </p>

  <p>
    A non-exhaustive list of services that are expected to integrate
    with CAP over time:
  </p>
  <ul>
    <li>
      <strong>ATR</strong>, the Apache Trusted Release service
      (<a href="{ATR_URL}" target="_blank" rel="noopener">{ATR_URL}</a>),
      for release-vote workflows.
    </li>
    <li>
      <strong>.asf.yaml</strong> automation, for committee approvals on
      sensitive repository configuration changes.
    </li>
    <li>
      Infrastructure self-service tooling, for committee sign-off on
      operations that today rely on bespoke INFRA tickets and ad-hoc
      mailing-list threads.
    </li>
  </ul>

  <!-- ------------------------------------------------------------------ -->
  <!-- Resources / links                                                  -->
  <!-- ------------------------------------------------------------------ -->
  <h2 id="resources" class="h4 mt-5 mb-3">
    <i class="fa-solid fa-link me-2 text-primary"></i>
    Resources and contact
  </h2>

  <ul class="list-unstyled about-links">
    <li>
      <i class="fa-solid fa-code me-2 text-primary"></i>
      <strong>OpenAPI spec:</strong>
      <a href="{config.API_BASE}/api" target="_blank" rel="noopener">
        {config.API_BASE}/api
      </a>
      (machine-readable schema for every endpoint)
    </li>
    <li>
      <i class="fa-solid fa-book me-2 text-primary"></i>
      <strong>Swagger docs:</strong>
      <a href="{config.API_BASE}/docs" target="_blank" rel="noopener">
        {config.API_BASE}/docs
      </a>
      (interactive API browser)
    </li>
    <li>
      <i class="fa-brands fa-github me-2 text-primary"></i>
      <strong>Source code:</strong>
      <a href="{REPO_URL}" target="_blank" rel="noopener">{REPO_URL}</a>
      (public GitHub repository for the CAP backend, frontend, and spec)
    </li>
    <li>
      <i class="fa-solid fa-envelope me-2 text-primary"></i>
      <strong>Questions and feedback:</strong>
      <a href="mailto:{CONTACT_LIST}">{CONTACT_LIST}</a>,
      or open an issue or pull request on the
      <a href="{REPO_URL}/issues" target="_blank" rel="noopener">GitHub
      tracker</a>.
    </li>
  </ul>

  <div class="text-center mt-5 mb-2">
    <a class="btn btn-outline-primary" href="/" use:link>
      <i class="fa-solid fa-house me-1"></i>Return to dashboard
    </a>
  </div>
</div>

<style>
  .about-page {
    line-height: 1.55;
  }

  .about-page p {
    margin-bottom: 0.9rem;
  }

  .about-page h2 {
    scroll-margin-top: 1rem;
  }

  .about-links li {
    margin-bottom: 0.5rem;
  }

  .workflow-chart {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 0;
  }

  .wf-step {
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    background: #fff;
    border: 1px solid rgba(0, 0, 0, 0.075);
    border-left: 4px solid var(--bs-primary);
    border-radius: 0.375rem;
    padding: 1rem 1.25rem;
  }

  .wf-step-icon {
    flex: 0 0 auto;
    width: 2.25rem;
    height: 2.25rem;
    border-radius: 50%;
    background: rgba(58, 94, 140, 0.1);
    color: var(--bs-primary);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
    margin-top: 0.1rem;
  }

  .wf-step-body {
    flex: 1 1 auto;
    min-width: 0;
  }

  .wf-step-title {
    font-weight: 600;
    margin-bottom: 0.2rem;
  }

  .wf-step-text {
    color: var(--bs-body-color);
  }

  .wf-step-resolve .wf-step-text {
    margin-bottom: 0.5rem;
  }

  .wf-arrow {
    align-self: center;
    color: var(--bs-secondary);
    padding: 0.4rem 0;
    font-size: 1.1rem;
    line-height: 1;
  }
</style>
