// Jobs array populated asynchronously.
// Frontend script for job listings page.
let jobs = [];

// Jobs data source (Supabase Storage JSON).
const JOBS_DATA_URL = 'https://tokzbiepijjdvbdtacjz.supabase.co/storage/v1/object/public/jobs-info/jobs.json';
const JOB_DETAILS_URL = 'https://tokzbiepijjdvbdtacjz.supabase.co/storage/v1/object/public/jobs-info/jobsDetails.json';

// Determine the base URL for API requests.
// Use the hosted API base for details fetches.
const REMOTE_API_BASE = 'https://govt-jobs-site.onrender.com';
const isFileProtocol = window.location.protocol === 'file:';
const isLocalhost =
  window.location.hostname === 'localhost' ||
  window.location.hostname === '127.0.0.1';
const API_BASE = '';  
const API_ENABLED = Boolean(REMOTE_API_BASE);

// THE List of all Indian states and union territories. This is used both to
// populate the state filter and to infer a state for jobs that are not
// explicitly tagged with one.  If you update this list, be sure to keep
// the names in their official form (e.g. "Andaman and Nicobar Islands")
// to improve matching quality.
const ALL_STATES = [
  'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
  'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand', 'Karnataka',
  'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram',
  'Nagaland', 'Odisha', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu',
  'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
  'Andaman and Nicobar Islands', 'Chandigarh', 'Dadra and Nagar Haveli and Daman and Diu',
  'Delhi', 'Jammu and Kashmir', 'Ladakh', 'Lakshadweep', 'Puducherry'
];

/**
 * Attempt to infer the Indian state associated with a job by searching for
 * state keywords within the job title and board fields.  If a match is
 * found, the corresponding state name is returned.  Matching is case
 * insensitive and considers partial matches of words longer than two
 * characters to avoid accidental false positives.
 *
 * @param {Object} job A job object containing at least a title or board.
 * @returns {string|null} The inferred state name, or null if none matched.
 */
function inferStateForJob(job) {
  if (!job) return null;
  const text = ((job.title || '') + ' ' + (job.board || '')).toLowerCase();
  for (const state of ALL_STATES) {
    const keywords = state.toLowerCase().split(/\s+/);
    for (const kw of keywords) {
      // Ignore very short tokens (e.g. 'of', 'and') and only match tokens
      // longer than two characters to reduce noise.
      if (kw.length > 2 && text.includes(kw)) {
        return state;
      }
    }
  }
  return null;
}

/**
 * Augment a job object with derived fields such as postCount and state.
 * - Computes postCount by parsing numbers from the title if not already present.
 * - Ensures state property exists.
 * - Explicitly tags jobs mentioning JK/J&K as Jammu and Kashmir.
 * - Infers state from title/board when still missing.
 * @param {Object} job
 */
function processJob(job) {
  // Compute postCount if missing
  if (job.postCount === undefined || job.postCount === null) {
    const match = job.title && job.title.match(/(\d+[,.]?\d*)\s*Posts?/i);
    job.postCount = match ? parseInt(match[1].replace(/,/g, ''), 10) : null;
  }
  // Ensure state property exists
  if (!('state' in job) || job.state === undefined) {
    job.state = null;
  }
  // Tag JK-specific jobs to Jammu and Kashmir
  const textLC = `${job.title || ''} ${job.board || ''}`.toLowerCase();
  if (!job.state) {
    if (textLC.includes(' j&k') || textLC.includes('j&k ') || textLC.includes(' jk ') ||
        textLC.includes('jkssb') || textLC.includes('jkpsc') ||
        textLC.includes(' jammu') || textLC.includes(' kashmir')) {
      job.state = 'Jammu and Kashmir';
    }
  }
  // Infer state if still missing
  if (!job.state) {
    const inferred = inferStateForJob(job);
    if (inferred) job.state = inferred;
  }
}

/**
 * Process an array of jobs using processJob.
 * @param {Array} list
 */
function processJobList(list) {
  list.forEach((job) => processJob(job));
}

function dedupeJobsByKey(list) {
  const seen = new Set();
  const deduped = [];
  list.forEach((job) => {
    const key = job.url || job.title;
    if (!key || seen.has(key)) return;
    seen.add(key);
    deduped.push(job);
  });
  return deduped;
}

function getActiveFilters() {
  return {
    keyword: document.getElementById('keyword').value.trim().toLowerCase(),
    qualification: document.getElementById('qualification').value,
    board: document.getElementById('board').value,
    state: document.getElementById('state') ? document.getElementById('state').value : '',
    sortBy: document.getElementById('sort-options').value
  };
}

let activeMonthFilter = null;

function applyFiltersFromState({ preservePage = false } = {}) {
  const { keyword, qualification, board, state, sortBy } = getActiveFilters();

  let filtered = jobs.filter(job => {
    const keywordMatch =
      job.title.toLowerCase().includes(keyword) ||
      job.board.toLowerCase().includes(keyword) ||
      (job.state && job.state.toLowerCase().includes(keyword));
    const qualMatch = qualification ? job.qualification === qualification : true;
    const boardMatch = board ? job.board === board : true;
    const stateMatch = state ? (job.state ? job.state === state : false) : true;
    let monthMatch = true;
    if (activeMonthFilter) {
      const jobDate = new Date(job.lastDate);
      if (Number.isNaN(jobDate.getTime())) {
        monthMatch = false;
      } else {
        monthMatch =
          jobDate.getFullYear() === activeMonthFilter.year &&
          jobDate.getMonth() === activeMonthFilter.month;
      }
    }
    return keywordMatch && qualMatch && boardMatch && stateMatch && monthMatch;
  });

  filtered = sortJobs(filtered, sortBy || 'lastDateAsc');
  currentFilteredJobs = filtered;
  if (!preservePage) {
    currentPage = 1;
  } else {
    const totalPages = Math.max(1, Math.ceil(currentFilteredJobs.length / itemsPerPage));
    if (currentPage > totalPages) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;
  }
  renderPagination(currentFilteredJobs);
  renderResultsPage();
}
// Pagination state
let currentPage = 1;
const itemsPerPage = 12;
let currentFilteredJobs = [];

// Offset for API pagination; null when no further pages
let apiNextOffset = null;
let isHttpOrigin = false;
let apiLoading = false;

// Cache configuration for storing jobs between page reloads.  Jobs are cached
// in localStorage with a timestamp so that reloading the page doesn't
// immediately trigger a new scrape if fresh data is available.  The cache
// expires after one hour (1 * 60 * 60 * 1000 ms).  Using localStorage allows
// persistence across page reloads and even across browser sessions for the
// same origin.
const CACHE_KEY = 'jobsCache';
const CACHE_TIMESTAMP_KEY = 'jobsCacheTimestamp';
const CACHE_TTL = 60 * 60 * 1000; // 1 hour in milliseconds

// Interval in milliseconds between successive automatic refreshes of job
// listings from the API.  This allows the front‑end to stay up to date
// even after the initial load.  Set to 5 minutes by default.
const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

// Interval for background auto-fetching additional API pages so pagination grows
// without requiring the user to reach the last page. Set to 15 seconds.
const AUTO_LOAD_MORE_INTERVAL_MS = 15 * 1000;

let autoLoadMoreInFlight = false;

let detailsByUrl = {};

async function fetchJobsSnapshot() {
  const response = await fetch(JOBS_DATA_URL, { cache: 'no-store' });
  if (!response.ok) return [];
  const payload = await response.json();
  return Array.isArray(payload.jobs) ? payload.jobs : [];
}

async function fetchJobDetailsSnapshot() {
  const response = await fetch(JOB_DETAILS_URL, { cache: 'no-store' });
  if (!response.ok) return {};
  const payload = await response.json();
  if (payload && typeof payload === 'object') {
    if (payload.details && typeof payload.details === 'object') {
      return payload.details;
    }
  }
  return {};
}

/**
 * Show or hide the global loading overlay.  When shown, it covers the
 * entire page and displays a spinner with a message.  The message can be
 * customized to distinguish between an initial load and a background
 * update.
 *
 * @param {boolean} show Whether to display the overlay.
 * @param {boolean} updating If true, show a different message indicating a background update.
 */
function showLoadingOverlay(show, updating = false) {
  const overlay = document.getElementById('loading-overlay');
  if (!overlay) return;
  if (show) {
    overlay.style.display = 'flex';
    const textEl = document.getElementById('loading-text');
    if (textEl) {
      textEl.textContent = updating ? 'Updating jobs…' : 'Loading jobs…';
    }
  } else {
    overlay.style.display = 'none';
  }
}

/**
 * Store the current jobs array in sessionStorage along with a timestamp.  This
 * helper should be called whenever the jobs list is updated from the API so
 * that subsequent page reloads can reuse the cached results without waiting
 * for a full scrape to complete again.  Only jobs served from HTTP origins
 * are cached; fallback datasets and static pages are not persisted across
 * reloads.
 */
function cacheJobs() {
  try {
    // Only cache when there is at least one job.  Use localStorage so data
    // persists across reloads and browser sessions for the same origin.
    if (Array.isArray(jobs) && jobs.length) {
      localStorage.setItem(CACHE_KEY, JSON.stringify(jobs.map(job => {
        const { id, ...rest } = job;
        return rest;
      })));
      localStorage.setItem(CACHE_TIMESTAMP_KEY, Date.now().toString());
    }
  } catch (e) {
    console.warn('Unable to cache jobs', e);
  }
}

/**
 * Update the results header to show a loading message or the count of jobs found.
 * @param {boolean} loading
 */
function setLoadingMessage(loading, updating = false) {
  const resultsCountEl = document.getElementById('results-count');
  if (!resultsCountEl) return;
  if (loading) {
    // If updating, show a different message to indicate background refresh
    resultsCountEl.textContent = updating ? 'Updating jobs…' : 'Loading jobs…';
  } else {
    resultsCountEl.textContent = `${currentFilteredJobs.length} Job${currentFilteredJobs.length !== 1 ? 's' : ''} Found`;
  }
}


/**
 * Load jobs either from the API (when served over HTTP) or from the global
 * realJobs variable (when opened as a static file).  If neither is
 * available, fall back to a small sample dataset.
 */
async function loadJobs() {
  // Determine if we are running from an HTTP origin (e.g. http://localhost)
  isHttpOrigin = window.location.protocol.startsWith('http');
  const SNAPSHOT_URL = JOBS_DATA_URL;
  // Attempt to load cached jobs from localStorage regardless of protocol
  let usedCache = false;
  try {
    const cachedJobsStr = localStorage.getItem(CACHE_KEY);
    const tsStr = localStorage.getItem(CACHE_TIMESTAMP_KEY);
    if (cachedJobsStr && tsStr) {
      const ts = parseInt(tsStr, 10);
      if (!isNaN(ts) && (Date.now() - ts) < CACHE_TTL) {
        const parsed = JSON.parse(cachedJobsStr);
        if (Array.isArray(parsed) && parsed.length) {
          // Use cached jobs
          jobs = parsed.map((job, idx) => ({ id: idx + 1, ...job }));
          processJobList(jobs);
          populateFilters();
          applyFiltersFromState();
          toggleLoadMore();
          setLoadingMessage(false);
          usedCache = true;
        }
      }
    }
  } catch (e) {
    console.warn('Failed to parse cached jobs', e);
  }
  // Determine if we are running from an HTTP origin.  If the page is
  // served via file:// but API_BASE is non-empty (meaning we have a base
  // URL for API calls), treat this as if it were HTTP for the purposes
  // of updating the cache from the server.
  isHttpOrigin = window.location.protocol.startsWith('http');
  if (usedCache) {
    // Update in background if we have a cache and a reachable API.  When
    // API_BASE is non-empty (file mode with local server), treat this as
    // accessible even when not served via HTTP.
    if (isHttpOrigin || API_BASE) {
      showLoadingOverlay(true, true);
      try {
        setLoadingMessage(true, true);
        const fetched = await fetchJobsSnapshot();
        if (fetched.length) {
          const merged = dedupeJobsByKey([...jobs, ...fetched]);
          jobs = merged.map((job, idx) => ({ id: idx + 1, ...job }));
          processJobList(jobs);
          populateFilters();
          applyFiltersFromState();
          toggleLoadMore();
          cacheJobs();
        }
        const details = await fetchJobDetailsSnapshot();
        if (details && typeof details === 'object') {
          detailsByUrl = details;
        }
      } catch (err) {
        console.error('Failed to fetch jobs in background', err);
      }
      showLoadingOverlay(false);
      setLoadingMessage(false);
    }
    return;
  }
  // No valid cache; attempt snapshot only
  if (isHttpOrigin || API_BASE) {
    // Show loading overlay and message
    showLoadingOverlay(true);
    setLoadingMessage(true);
    try {
      const snapJobs = await fetchJobsSnapshot();
      if (snapJobs.length) {
        jobs = snapJobs.map((job, idx) => ({ id: idx + 1, ...job }));
        processJobList(jobs);
        populateFilters();
        applyFiltersFromState();
        toggleLoadMore();
        const details = await fetchJobDetailsSnapshot();
        if (details && typeof details === 'object') {
          detailsByUrl = details;
        }
        showLoadingOverlay(false);
        setLoadingMessage(false);
        cacheJobs();
        return;
      }
    } catch (error) {
      console.error('Failed to fetch snapshot', error);
    }
    showLoadingOverlay(false);
    setLoadingMessage(false);
  }
  // No fallback dataset; snapshot is the only source.
  jobs = [];
  populateFilters();
  applyFiltersFromState();
  toggleLoadMore();
  setLoadingMessage(false);
}

// Utility to format dates nicely
function formatDate(dateStr) {
  if (!dateStr) return 'N/A';
  const parsed = new Date(dateStr);
  if (Number.isNaN(parsed.getTime())) return dateStr;
  const options = { year: 'numeric', month: 'short', day: 'numeric' };
  return parsed.toLocaleDateString('en-IN', options);
}

// Populate dynamic filter options (board and qualification) based on loaded jobs
function populateFilters() {
  // Populate boards
  const boardSelect = document.getElementById('board');
  const selectedBoard = boardSelect.value;
  // Preserve the first option (default placeholder)
  const defaultBoardOption = boardSelect.options[0];
  boardSelect.innerHTML = '';
  boardSelect.appendChild(defaultBoardOption);
  const boards = new Set();
  jobs.forEach(job => {
    if (job.board) boards.add(job.board);
  });
  Array.from(boards).sort().forEach(board => {
    const opt = document.createElement('option');
    opt.value = board;
    opt.textContent = board;
    boardSelect.appendChild(opt);
  });
  if (selectedBoard) {
    boardSelect.value = selectedBoard;
  }
  // Populate qualifications
  const qualSelect = document.getElementById('qualification');
  const selectedQualification = qualSelect.value;
  const defaultQualOption = qualSelect.options[0];
  qualSelect.innerHTML = '';
  qualSelect.appendChild(defaultQualOption);
  const quals = new Set();
  jobs.forEach(job => {
    if (job.qualification) {
      // Qualifications may be comma separated; split and add individually
      job.qualification.split(/,\s*/).forEach(q => quals.add(q));
    }
  });
  Array.from(quals).sort().forEach(q => {
    const opt = document.createElement('option');
    opt.value = q;
    opt.textContent = q;
    qualSelect.appendChild(opt);
  });
  if (selectedQualification) {
    qualSelect.value = selectedQualification;
  }

  // Populate states with all Indian states and union territories
  const stateSelect = document.getElementById('state');
  if (stateSelect) {
    const selectedState = stateSelect.value;
    const defaultStateOption = stateSelect.options[0];
    stateSelect.innerHTML = '';
    stateSelect.appendChild(defaultStateOption);
    // Use constant list ALL_STATES for state filter
    ALL_STATES.slice().sort().forEach(st => {
      const opt = document.createElement('option');
      opt.value = st;
      opt.textContent = st;
      stateSelect.appendChild(opt);
    });
    if (selectedState) {
      stateSelect.value = selectedState;
    }
  }
}

// Render job cards to the page
function renderJobs(jobArray) {
  const jobsList = document.getElementById('jobs-list');
  jobsList.innerHTML = '';
  jobArray.forEach(job => {
    const card = document.createElement('div');
    card.className = 'job-card';
    // Render job card with a button that opens the modal instead of navigating to a details page.
    // A button is used here so that the event can trigger openModal(job.id) while
    // maintaining consistent styling via the btn-details class.
    card.innerHTML = `
      <h3>${job.title}</h3>
      <div class="job-meta"><strong>Board:</strong> ${job.board}</div>
      <div class="job-meta"><strong>Qualification:</strong> ${job.qualification}</div>
      <div class="job-meta"><strong>Last Date:</strong> ${formatDate(job.lastDate)}</div>
    `;
    const detailsButton = document.createElement('button');
    detailsButton.className = 'btn-details';
    detailsButton.textContent = 'View Details';
    detailsButton.addEventListener('click', () => openModal(job.id));
    card.appendChild(detailsButton);
    jobsList.appendChild(card);
  });
  // Note: results count is updated elsewhere (filterJobs)
}

// Render pagination controls based on current filtered jobs
function renderPagination(totalJobs) {
  const paginationEl = document.getElementById('pagination');
  if (!paginationEl) return;
  paginationEl.innerHTML = '';
  const totalPages = Math.ceil(totalJobs.length / itemsPerPage);
  if (totalPages <= 1) return;
  // Previous button
  const prevBtn = document.createElement('button');
  prevBtn.textContent = 'Prev';
  prevBtn.disabled = currentPage === 1;
  prevBtn.addEventListener('click', () => {
    if (currentPage > 1) {
      currentPage--;
      renderResultsPage();
    }
  });
  paginationEl.appendChild(prevBtn);

  // Page dropdown centered between Prev and Next
  const pageSelect = document.createElement('select');
  pageSelect.className = 'pagination-select';
  for (let i = 1; i <= totalPages; i++) {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = `Page ${i} of ${totalPages}`;
    if (i === currentPage) opt.selected = true;
    pageSelect.appendChild(opt);
  }
  pageSelect.addEventListener('change', (e) => {
    const value = parseInt(e.target.value, 10);
    if (!Number.isNaN(value)) {
      currentPage = value;
      renderResultsPage();
    }
  });
  paginationEl.appendChild(pageSelect);

  // Next button
  const nextBtn = document.createElement('button');
  nextBtn.textContent = 'Next';
  nextBtn.disabled = currentPage === totalPages;
  nextBtn.addEventListener('click', () => {
    if (currentPage < totalPages) {
      currentPage++;
      renderResultsPage();
    }
  });
  paginationEl.appendChild(nextBtn);
}

// Render current page of filtered results
function renderResultsPage() {
  const start = (currentPage - 1) * itemsPerPage;
  const end = start + itemsPerPage;
  const slice = currentFilteredJobs.slice(start, end);
  renderJobs(slice);
  // Re-render pagination to keep Prev/Next disabled states in sync
  renderPagination(currentFilteredJobs);
  // Update results count showing total filtered jobs
  const resultsCountEl = document.getElementById('results-count');
  if (resultsCountEl) {
    resultsCountEl.textContent = `${currentFilteredJobs.length} Job${currentFilteredJobs.length !== 1 ? 's' : ''} Found`;
  }
  // Update pagination buttons (active state)
  const paginationEl = document.getElementById('pagination');
  if (paginationEl) {
    const select = paginationEl.querySelector('.pagination-select');
    if (select) {
      select.value = currentPage.toString();
    }
  }
  // Toggle the visibility of the load more button based on current page and API offset
  toggleLoadMore();
}

/**
 * Show or hide the load more button depending on whether more jobs are available.
 * The button is displayed only when served over HTTP, additional pages are
 * available from the backend, and the user has reached the last page of
 * the current filtered results.
 */
function toggleLoadMore() {
  const container = document.getElementById('load-more-container');
  if (!container) return;
  const totalPages = Math.ceil(currentFilteredJobs.length / itemsPerPage);
  if (isHttpOrigin && (apiNextOffset !== null || apiLoading) && currentPage >= totalPages) {
    container.style.display = 'block';
  } else {
    container.style.display = 'none';
  }
}

/**
 * Load additional jobs from the backend when the load more button is clicked.
 * Appends new jobs to the global jobs array, processes them, updates filters
 * and re-renders pagination and current page.
 */
async function loadMoreJobs() {
  // Only fetch more jobs when using the API and there is a next offset
  if (!isHttpOrigin || (apiNextOffset === null && !apiLoading)) return;
  if (autoLoadMoreInFlight) return;
  // Grab the button to update its state
  const loadBtn = document.getElementById('load-more-btn');
  if (loadBtn) {
    loadBtn.textContent = 'Loading...';
    loadBtn.disabled = true;
  }
  autoLoadMoreInFlight = true;
  try {
    const offset = apiNextOffset !== null ? apiNextOffset : jobs.length;
    const response = await fetch(`${API_BASE}/api/jobs?offset=${offset}`);
    if (response.ok) {
      const data = await response.json();
      const newJobs = Array.isArray(data.jobs) ? data.jobs : [];
      const startId = jobs.length + 1;
      newJobs.forEach((jobData, idx) => {
        const job = { id: startId + idx, ...jobData };
        processJob(job);
        jobs.push(job);
      });
      apiNextOffset = data.next_offset;
      apiLoading = !!data.loading;
      // Repopulate filters to include any new boards, qualifications or states
      populateFilters();
      // Resort and reapply filters without resetting pagination
      applyFiltersFromState({ preservePage: true });
      // Update cache with appended jobs
      cacheJobs();
    }
  } catch (error) {
    console.error('Failed to load more jobs', error);
  } finally {
    autoLoadMoreInFlight = false;
  }
  // Restore button text
  if (loadBtn) {
    loadBtn.textContent = 'Load More Jobs';
    loadBtn.disabled = false;
  }
}

/**
 * Auto-fetch additional pages in the background so pagination grows
 * without requiring the user to reach the last page.
 */
async function autoLoadMoreJobs() {
  if (!isHttpOrigin || (apiNextOffset === null && !apiLoading)) return;
  if (autoLoadMoreInFlight) return;
  // Load additional jobs silently (no button state changes)
  try {
    autoLoadMoreInFlight = true;
    while (true) {
      if (apiNextOffset === null && !apiLoading) break;
      const offset = apiNextOffset !== null ? apiNextOffset : jobs.length;
      const response = await fetch(`${API_BASE}/api/jobs?offset=${offset}`);
      if (!response.ok) break;
      const data = await response.json();
      const newJobs = Array.isArray(data.jobs) ? data.jobs : [];
      apiNextOffset = data.next_offset;
      apiLoading = !!data.loading;
      if (!newJobs.length) {
        if (apiNextOffset === null && !apiLoading) break;
        // No new jobs yet; exit the loop and try again on next interval
        break;
      }
      const startId = jobs.length + 1;
      newJobs.forEach((jobData, idx) => {
        const job = { id: startId + idx, ...jobData };
        processJob(job);
        jobs.push(job);
      });
      populateFilters();
      applyFiltersFromState({ preservePage: true });
      cacheJobs();
      await new Promise(resolve => setTimeout(resolve, 300));
    }
  } catch (error) {
    console.error('Failed to auto-load more jobs', error);
  } finally {
    autoLoadMoreInFlight = false;
  }
}

// Filter jobs based on selected filters
function filterJobs() {
  applyFiltersFromState();
}

// Sort jobs based on selected criteria
function sortJobs(arr, criterion) {
  const sorted = [...arr];
  switch (criterion) {
    case 'lastDateAsc':
      sorted.sort((a, b) => new Date(a.lastDate) - new Date(b.lastDate));
      break;
    case 'lastDateDesc':
      sorted.sort((a, b) => new Date(b.lastDate) - new Date(a.lastDate));
      break;
    default:
      // default ascending
      sorted.sort((a, b) => new Date(a.lastDate) - new Date(b.lastDate));
      break;
  }
  return sorted;
}

// Event listeners
document.getElementById('search-btn').addEventListener('click', filterJobs);
document.getElementById('sort-options').addEventListener('change', () => {
  filterJobs();
});

// Trigger filtering when state, board, or qualification selections change
const stateSelectEl = document.getElementById('state');
if (stateSelectEl) stateSelectEl.addEventListener('change', filterJobs);
const boardSelectEl = document.getElementById('board');
if (boardSelectEl) boardSelectEl.addEventListener('change', filterJobs);
const qualificationSelectEl = document.getElementById('qualification');
if (qualificationSelectEl) qualificationSelectEl.addEventListener('change', filterJobs);

// Initial load
loadJobs();

function updateMonthFilterLabels() {
  const monthSelect = document.getElementById('month-filter');
  if (!monthSelect) return;
  const base = new Date();
  const month2 = new Date(base.getFullYear(), base.getMonth() + 2, 1);
  const options = monthSelect.querySelectorAll('option');
  options.forEach((opt) => {
    if (opt.value === 'this') opt.textContent = 'This month';
    if (opt.value === 'next') opt.textContent = 'Next month';
    if (opt.value === 'next2') opt.textContent = month2.toLocaleString('en-IN', { month: 'long' });
  });
}

function setMonthFilterFromSelect() {
  const monthSelect = document.getElementById('month-filter');
  if (!monthSelect) return;
  const base = new Date();
  const value = monthSelect.value;
  if (!value) {
    activeMonthFilter = null;
    return;
  }
  const offset = value === 'this' ? 0 : value === 'next' ? 1 : 2;
  const targetDate = new Date(base.getFullYear(), base.getMonth() + offset, 1);
  activeMonthFilter = { year: targetDate.getFullYear(), month: targetDate.getMonth() };
}

function clearAllFilters() {
  const keywordInput = document.getElementById('keyword');
  const qualificationSelect = document.getElementById('qualification');
  const boardSelect = document.getElementById('board');
  const stateSelect = document.getElementById('state');
  const sortSelect = document.getElementById('sort-options');
  const monthSelect = document.getElementById('month-filter');
  if (keywordInput) keywordInput.value = '';
  if (qualificationSelect) qualificationSelect.value = '';
  if (boardSelect) boardSelect.value = '';
  if (stateSelect) stateSelect.value = '';
  if (sortSelect) sortSelect.value = 'lastDateAsc';
  if (monthSelect) monthSelect.value = '';
  activeMonthFilter = null;
  applyFiltersFromState();
}

updateMonthFilterLabels();
const monthSelect = document.getElementById('month-filter');
if (monthSelect) {
  monthSelect.addEventListener('change', () => {
    setMonthFilterFromSelect();
    applyFiltersFromState();
  });
}
const clearFiltersBtn = document.getElementById('clear-filters');
if (clearFiltersBtn) clearFiltersBtn.addEventListener('click', clearAllFilters);

// Periodically refresh jobs from API every REFRESH_INTERVAL_MS when served over HTTP.
if (window.location.protocol.startsWith('http')) {
  setInterval(refreshJobs, REFRESH_INTERVAL_MS);
  setInterval(autoLoadMoreJobs, AUTO_LOAD_MORE_INTERVAL_MS);
}

// Load more button listener
const loadMoreBtn = document.getElementById('load-more-btn');
if (loadMoreBtn) {
  loadMoreBtn.addEventListener('click', loadMoreJobs);
}

// Modal logic
async function openModal(jobId) {
  const job = jobs.find(j => j.id === jobId);
  if (!job) return;
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };
  const normalizeLines = (items) => {
    if (!Array.isArray(items)) return [];
    const seen = new Set();
    const cleaned = [];
    items.forEach((item) => {
      const text = (item || '').toString().replace(/\s+/g, ' ').trim();
      if (!text || seen.has(text)) return;
      seen.add(text);
      cleaned.push(text);
    });
    return cleaned;
  };
  const appendListSection = (container, title, items, ordered = false) => {
    const cleaned = normalizeLines(items);
    if (!cleaned.length) return;
    const sec = document.createElement('div');
    const tag = ordered ? 'ol' : 'ul';
    sec.innerHTML = `<h4>${title}</h4><${tag}>${cleaned.map(item => `<li>${item}</li>`).join('')}</${tag}>`;
    container.appendChild(sec);
  };
  const appendDatesTable = (container, rows) => {
    if (!Array.isArray(rows) || !rows.length) return;
    const sec = document.createElement('div');
    const bodyRows = rows
      .map(row => {
        const eventText = (row.event || '').toString().trim();
        const dateText = (row.date || '').toString().trim();
        return eventText || dateText ? `<tr><td>${eventText}</td><td>${dateText}</td></tr>` : '';
      })
      .filter(Boolean)
      .join('');
    if (!bodyRows) return;
    sec.innerHTML = '<h4>Important Dates</h4>' +
      '<table class="modal-table">' +
      '<thead><tr><th>Event</th><th>Date</th></tr></thead>' +
      `<tbody>${bodyRows}</tbody>` +
      '</table>';
    container.appendChild(sec);
  };
  // Populate basic fields
  setText('modal-title', job.title);
  setText('modal-board', job.board);
  setText('modal-qualification', job.qualification || 'N/A');
  const sourceSpan = document.getElementById('modal-source');
  sourceSpan.innerHTML = '';
  if (job.url && job.url !== '#') {
    const sourceLink = document.createElement('a');
    sourceLink.href = job.url;
    sourceLink.target = '_blank';
    sourceLink.rel = 'noopener noreferrer';
    sourceLink.textContent = job.source;
    sourceSpan.appendChild(sourceLink);
  } else {
    sourceSpan.textContent = job.source;
  }
  setText('modal-company', job.companyName || 'N/A');
  setText('modal-advt', job.advtNo || 'N/A');
  // Reset summary fields to defaults (may be overwritten later)
  setText('modal-postname', job.postName || job.title);
  setText('modal-postcount', job.noOfPosts || job.postCount || 'N/A');
  setText('modal-salary', job.salary || 'N/A');
  const ageFallback = Array.isArray(job.ageLimit) ? job.ageLimit.join(', ') : job.ageLimit;
  setText('modal-agelimit', ageFallback || 'N/A');
  const linkWrapper = document.getElementById('modal-link-wrapper');
  linkWrapper.innerHTML = '';
  // Add official link if available
  if (job.url && job.url !== '#') {
    const anchor = document.createElement('a');
    anchor.href = job.url;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    anchor.textContent = 'View Job Posting Source';
    anchor.style.color = '#2d64a8';
    linkWrapper.appendChild(anchor);
  }
  // Clear previous details
  const detailsDiv = document.getElementById('modal-details');
  detailsDiv.innerHTML = '';
  const importantDatesDiv = document.getElementById('modal-important-dates');
  importantDatesDiv.innerHTML = '';
  const selectionDiv = document.getElementById('modal-selection-process');
  selectionDiv.innerHTML = '';
  const instructionsDiv = document.getElementById('modal-general-instructions');
  instructionsDiv.innerHTML = '';
  const applyDiv = document.getElementById('modal-how-to-apply');
  applyDiv.innerHTML = '';
  const linksDiv = document.getElementById('modal-important-links');
  linksDiv.innerHTML = '';
  const buildLinksList = (links) => {
    const list = document.createElement('ul');
    links.forEach(({ label, text, url }) => {
      const item = document.createElement('li');
      const labelText = label ? `${label} ` : '';
      if (labelText) {
        item.appendChild(document.createTextNode(labelText));
      }
      if (url && text) {
        const a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = text;
        item.appendChild(a);
      } else if (text) {
        item.appendChild(document.createTextNode(text));
      }
      list.appendChild(item);
    });
    return list;
  };
  // If served over HTTP and job URL exists, fetch extra details from API
  // Determine if we should attempt to fetch extra details.  When API_BASE is defined
  // (even in file:// mode) and a job URL exists, fetch details via the backend.
  const detailApiBases = [];
  if (REMOTE_API_BASE && !detailApiBases.includes(REMOTE_API_BASE)) {
    detailApiBases.push(REMOTE_API_BASE);
  }
  const storedDetails = job.url && detailsByUrl ? detailsByUrl[job.url] : null;
  if (storedDetails) {
    const data = storedDetails;
    if (data.postName) setText('modal-postname', data.postName);
    if (data.noOfPosts) setText('modal-postcount', data.noOfPosts);
    if (data.salary) setText('modal-salary', data.salary);
    if (data.ageLimit) setText('modal-agelimit', Array.isArray(data.ageLimit) ? data.ageLimit.join(', ') : data.ageLimit);
    if (data.companyName) setText('modal-company', data.companyName);
    if (data.advtNo) setText('modal-advt', data.advtNo);
    if (data.qualification) setText('modal-qualification', data.qualification);
    if (Array.isArray(data.importantDatesTable) && data.importantDatesTable.length) {
      appendDatesTable(importantDatesDiv, data.importantDatesTable);
    }
    const datesList = [];
    if (data.startDate) {
      datesList.push(`Start Date to Apply: ${formatDate(data.startDate)}`);
    }
    if (data.lastDate) {
      datesList.push(`Last Date to Apply: ${formatDate(data.lastDate)}`);
    }
    if (Array.isArray(data.importantDates) && data.importantDates.length) {
      datesList.push(...data.importantDates);
    }
    appendListSection(importantDatesDiv, 'Important Dates', datesList);
    const linksPayload = [];
    if (Array.isArray(data.officialWebsites)) {
      const sites = data.officialWebsites.slice(0, 2).filter(Boolean);
      sites.forEach((site) => {
        const domain = site.replace(/^https?:\/\//, '').split('/')[0];
        linksPayload.push({
          label: 'Official Website:',
          text: domain,
          url: site
        });
      });
    }
    if (Array.isArray(data.importantLinks) && data.importantLinks.length) {
      const notifications = data.importantLinks.filter(link => link.type === 'officialNotification');
      notifications.forEach((notif) => {
        linksPayload.push({
          label: notif.label,
          text: notif.display,
          url: notif.url
        });
      });
    }
    if (job.url && job.url !== '#') {
      const linkWrapper = document.getElementById('modal-link-wrapper');
      if (linkWrapper && !linkWrapper.childElementCount) {
        const anchor = document.createElement('a');
        anchor.href = job.url;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        anchor.textContent = 'View Job Posting Source';
        anchor.style.color = '#2d64a8';
        linkWrapper.appendChild(anchor);
      }
    }
    if (!linksPayload.length && data.officialNotificationStatus) {
      linksPayload.push({
        label: '',
        text: data.officialNotificationStatus,
        url: ''
      });
    }
    if (linksPayload.length) {
      const sec = document.createElement('div');
      sec.innerHTML = '<h4>Important Links</h4>';
      sec.appendChild(buildLinksList(linksPayload));
      linksDiv.appendChild(sec);
    }
    appendListSection(detailsDiv, 'Salary/Stipend', data.salaryDetails);
    appendListSection(detailsDiv, 'Eligibility Criteria', data.eligibility);
    appendListSection(detailsDiv, 'Essential Requirements', data.desirableSkills);
    appendListSection(detailsDiv, 'Experience', data.experience);
    appendListSection(selectionDiv, 'Selection Process', data.selectionProcess);
    appendListSection(instructionsDiv, 'General Instructions', data.generalInstructions);
    appendListSection(applyDiv, 'How to Apply', data.howToApply, true);
  }

  const canFetchDetails = detailApiBases.length > 0 && job.url && job.url !== '#' && !storedDetails;
  if (canFetchDetails) {
    try {
      const params = new URLSearchParams({ url: job.url });
      let data = null;
      let lastStatus = null;
      let lastError = null;
      const attemptedBases = [];
      for (const base of detailApiBases) {
        try {
          attemptedBases.push(base);
          const response = await fetch(`${base}/api/job_details?${params.toString()}`);
          lastStatus = response.status;
          if (!response.ok) {
            continue;
          }
          data = await response.json();
          break;
        } catch (err) {
          lastError = err;
          continue;
        }
      }
      if (data) {
        // Fill summary fields if provided
        if (data.postName) setText('modal-postname', data.postName);
        if (data.noOfPosts) setText('modal-postcount', data.noOfPosts);
        if (data.salary) setText('modal-salary', data.salary);
        if (data.ageLimit) setText('modal-agelimit', Array.isArray(data.ageLimit) ? data.ageLimit.join(', ') : data.ageLimit);
        if (data.companyName) setText('modal-company', data.companyName);
        if (data.advtNo) setText('modal-advt', data.advtNo);
        if (data.qualification) setText('modal-qualification', data.qualification);
        // Display extracted details if present
        if (Array.isArray(data.importantDatesTable) && data.importantDatesTable.length) {
          appendDatesTable(importantDatesDiv, data.importantDatesTable);
        }
        const datesList = [];
        if (data.startDate) {
          datesList.push(`Start Date to Apply: ${formatDate(data.startDate)}`);
        }
        if (data.lastDate) {
          datesList.push(`Last Date to Apply: ${formatDate(data.lastDate)}`);
        }
        if (Array.isArray(data.importantDates) && data.importantDates.length) {
          datesList.push(...data.importantDates);
        }
        appendListSection(importantDatesDiv, 'Important Dates', datesList);
        const linksPayload = [];
        if (Array.isArray(data.officialWebsites)) {
          const sites = data.officialWebsites.slice(0, 2).filter(Boolean);
          sites.forEach((site) => {
            const domain = site.replace(/^https?:\/\//, '').split('/')[0];
            linksPayload.push({
              label: 'Official Website:',
              text: domain,
              url: site
            });
          });
        }
        if (Array.isArray(data.importantLinks) && data.importantLinks.length) {
          const notifications = data.importantLinks.filter(link => link.type === 'officialNotification');
          notifications.forEach((notif) => {
            linksPayload.push({
              label: notif.label,
              text: notif.display,
              url: notif.url
            });
          });
        }
        // View Job Posting Source is handled by modal-link-wrapper; keep it out of Important Links.
        if (!linksPayload.length && data.officialNotificationStatus) {
          linksPayload.push({
            label: '',
            text: data.officialNotificationStatus,
            url: ''
          });
        }
        if (linksPayload.length) {
          const sec = document.createElement('div');
          sec.innerHTML = '<h4>Important Links</h4>';
          sec.appendChild(buildLinksList(linksPayload));
          linksDiv.appendChild(sec);
        }
        appendListSection(detailsDiv, 'Salary/Stipend', data.salaryDetails);
        appendListSection(detailsDiv, 'Eligibility Criteria', data.eligibility);
        appendListSection(detailsDiv, 'Essential Requirements', data.desirableSkills);
        appendListSection(detailsDiv, 'Experience', data.experience);
        appendListSection(selectionDiv, 'Selection Process', data.selectionProcess);
        appendListSection(instructionsDiv, 'General Instructions', data.generalInstructions);
        appendListSection(applyDiv, 'How to Apply', data.howToApply, true);
        // Fallback: show first few lines of page text if nothing else captured
        if (!detailsDiv.childElementCount && data.html) {
          const snippet = data.html.split('\n').filter(l => l.trim()).slice(0, 10).join('<br>');
          const sec = document.createElement('div');
          sec.innerHTML = '<h4>Summary</h4><p>' + snippet + '</p>';
          detailsDiv.appendChild(sec);
        }
        if (!detailsDiv.childElementCount && !importantDatesDiv.childElementCount && !selectionDiv.childElementCount && !instructionsDiv.childElementCount && !applyDiv.childElementCount && !linksDiv.childElementCount) {
          const sec = document.createElement('div');
          sec.innerHTML = '<h4>Details Fetch</h4><p>API returned data, but no structured sections were parsed.</p>';
          detailsDiv.appendChild(sec);
        }
      } else {
        const sec = document.createElement('div');
        const statusText = lastStatus ? `Last status: ${lastStatus}.` : 'No HTTP response.';
        const errorText = lastError ? ` Error: ${lastError}` : '';
        const baseText = attemptedBases.length ? ` Attempted: ${attemptedBases.join(', ')}.` : '';
        sec.innerHTML = `<h4>Details Fetch Failed</h4><p>${statusText}${baseText}${errorText}</p>`;
        detailsDiv.appendChild(sec);
      }
    } catch (err) {
      console.error('Error fetching job details:', err);
      const sec = document.createElement('div');
      sec.innerHTML = `<h4>Details Fetch Failed</h4><p>${err}</p>`;
      detailsDiv.appendChild(sec);
    }
  }
  // Show modal
  const modal = document.getElementById('job-modal');
  modal.style.display = 'flex';

  // Prevent background from scrolling when modal is open
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('job-modal').style.display = 'none';
  // Restore scrolling on the page when modal is closed
  document.body.style.overflow = '';
}

/**
 * Refresh the job list from the API.  This function fetches the latest jobs
 * and, if data is returned, updates the global jobs array, reprocesses
 * derived fields, re-renders the UI and caches the results.  It shows an
 * updating overlay briefly during the fetch.  The function quietly exits
 * if the page is not served over HTTP or if the fetch fails.
 */
async function refreshJobs() {
  try {
    showLoadingOverlay(true, true);
    setLoadingMessage(true, true);
    const snapJobs = await fetchJobsSnapshot();
    if (!snapJobs.length) {
      showLoadingOverlay(false);
      setLoadingMessage(false);
      return;
    }
    const merged = dedupeJobsByKey([...jobs, ...snapJobs]);
    jobs = merged.map((job, idx) => ({ id: idx + 1, ...job }));
    processJobList(jobs);
    populateFilters();
    applyFiltersFromState({ preservePage: true });
    toggleLoadMore();
    cacheJobs();
  } catch (err) {
    console.error('Failed to refresh jobs', err);
  } finally {
    showLoadingOverlay(false);
    setLoadingMessage(false);
  }
}

// Attach close event
document.getElementById('modal-close').addEventListener('click', closeModal);
const modalBackBtn = document.getElementById('modal-back');
if (modalBackBtn) {
  modalBackBtn.addEventListener('click', closeModal);
}
// Close modal when clicking outside content
document.getElementById('job-modal').addEventListener('click', function(e) {
  if (e.target === this) {
    closeModal();
  }
});
