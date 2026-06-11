import { Link } from 'react-router-dom';

export default function OptOutPage() {
  return (
    <div className="app-main flex items-center justify-center" style={{ flex: 1, padding: 'var(--space-lg)' }}>
      <div className="archival-card text-center" style={{ maxWidth: 480, width: '100%' }}>
        <h2 style={{ marginBottom: 'var(--space-md)' }}>Invitation Declined</h2>
        <p className="text-muted" style={{ marginBottom: 'var(--space-lg)' }}>
          You have declined the consent agreement. No personal data has been saved, and your
          invitation remains uncompleted. If you change your mind, you may use the original
          invitation link to return to the onboarding page.
        </p>
        <Link to="/" className="btn btn-secondary">
          Return to Home
        </Link>
      </div>
    </div>
  );
}