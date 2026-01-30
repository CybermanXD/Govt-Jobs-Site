// This script drives the job details page.  It reads query parameters from
// Frontend script for job details page.
// the URL to obtain information about the selected job and fetches
// additional details from the backend API when available.  If the page is
// opened without HTTP (e.g. via file://), the API is not called and only
// basic fields passed in the query string are displayed.

/**
 * Format a date string (YYYY-MM-DD) into a more readable form.
 * Falls back to the original string when parsing fails.
 * @param {string} dateStr
 */
function formatDate(dateStr) {
  if (!dateStr) return '';
  try {
    const options = { year: 'numeric', month: 'short', day: 'numeric' };
    return new Date(dateStr).toLocaleDateString('en-IN', options);
  } catch (e) {
    return dateStr;
  }
}

async function loadJobDetails() {
  const params = new URLSearchParams(window.location.search);
  // Basic fields passed from the listing page
  const jobUrl = params.get('url');
  const title = params.get('title') ? decodeURIComponent(params.get('title')) : '';
  const board = params.get('board') ? decodeURIComponent(params.get('board')) : '';
  const qualification = params.get('qual') ? decodeURIComponent(params.get('qual')) : '';
  const lastDate = params.get('lastDate') ? decodeURIComponent(params.get('lastDate')) : '';
  const source = params.get('source') ? decodeURIComponent(params.get('source')) : '';
  const postCount = params.get('postCount') ? decodeURIComponent(params.get('postCount')) : '';
  const state = params.get('state') ? decodeURIComponent(params.get('state')) : '';

  const container = document.getElementById('job-detail');
  // Update breadcrumbs navigation
  const breadcrumbsEl = document.getElementById('breadcrumbs');
  if (breadcrumbsEl) {
    const safeTitle = title || '';
    breadcrumbsEl.innerHTML = `<a href="index.html">Home</a> &gt; ${safeTitle}`;
  }
  // Show basic summary while details load
  let html = '';
  html += `<h2>${title}</h2>`;
  if (board) html += `<p><strong>Recruiting Board:</strong> ${board}</p>`;
  if (postCount) html += `<p><strong>No of Posts:</strong> ${postCount || 'N/A'}</p>`;
  if (qualification) html += `<p><strong>Qualification Required:</strong> ${qualification}</p>`;
  if (state) html += `<p><strong>State:</strong> ${state}</p>`;
  if (lastDate) html += `<p><strong>Last Date to Apply:</strong> ${formatDate(lastDate)}</p>`;
  if (source) html += `<p><strong>Source:</strong> ${source}</p>`;
  if (jobUrl) {
    html += `<p><a href="${jobUrl}" target="_blank" rel="noopener noreferrer">View Official Notification</a></p>`;
  }
  // Placeholder for detailed sections
  html += '<div id="detail-sections"></div>';
  container.innerHTML = html;
  const apiEnabled =
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1' ||
    window.location.protocol === 'file:';
  // If local API enabled and jobUrl present, fetch detailed sections
  if (apiEnabled && jobUrl) {
    try {
      const resp = await fetch(`/api/job_details?url=${encodeURIComponent(jobUrl)}`);
      if (resp.ok) {
        const details = await resp.json();
        const sec = document.getElementById('detail-sections');
        // Append sections if present
        if (details.postName) {
          sec.innerHTML += `<p><strong>Post Name:</strong> ${details.postName}</p>`;
        }
        if (details.noOfPosts) {
          sec.innerHTML += `<p><strong>No of Posts:</strong> ${details.noOfPosts}</p>`;
        }
        if (details.salary) {
          sec.innerHTML += `<p><strong>Salary:</strong> ${details.salary}</p>`;
        }
        if (details.qualification) {
          sec.innerHTML += `<p><strong>Qualification Required:</strong> ${details.qualification}</p>`;
        }
        if (details.ageLimit && Array.isArray(details.ageLimit)) {
          sec.innerHTML += `<p><strong>Age Limit:</strong> ${details.ageLimit.join('<br>')}</p>`;
        }
        if (details.officialWebsite) {
          sec.innerHTML += `<p><strong>Official Website:</strong> <a href="${details.officialWebsite}" target="_blank" rel="noopener noreferrer">${details.officialWebsite}</a></p>`;
        }
        // Eligibility
        if (details.eligibility && details.eligibility.length) {
          sec.innerHTML += '<h3>Eligibility</h3>';
          sec.innerHTML += '<ul>' + details.eligibility.map(e => `<li>${e}</li>`).join('') + '</ul>';
        }
        // Desirable skills
        if (details.desirableSkills && details.desirableSkills.length) {
          sec.innerHTML += '<h3>Desirable Skills</h3>';
          sec.innerHTML += '<ul>' + details.desirableSkills.map(e => `<li>${e}</li>`).join('') + '</ul>';
        }
        // Experience
        if (details.experience && details.experience.length) {
          sec.innerHTML += '<h3>Experience</h3>';
          sec.innerHTML += '<ul>' + details.experience.map(e => `<li>${e}</li>`).join('') + '</ul>';
        }
        // Salary Details
        if (details.salaryDetails && details.salaryDetails.length) {
          sec.innerHTML += '<h3>Salary / Stipend Details</h3>';
          sec.innerHTML += '<ul>' + details.salaryDetails.map(e => `<li>${e}</li>`).join('') + '</ul>';
        }
        // Important dates
        if (details.importantDates && details.importantDates.length) {
          sec.innerHTML += '<h3>Important Dates</h3>';
          sec.innerHTML += '<ul>' + details.importantDates.map(e => `<li>${e}</li>`).join('') + '</ul>';
        }
      }
    } catch (err) {
      console.error('Failed to load job details', err);
    }
  }
}

document.addEventListener('DOMContentLoaded', loadJobDetails);
