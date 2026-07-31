import GoogleSignInButton from '../components/GoogleSignInButton'
import { useAuth } from '../auth/useAuth'

function Home() {
  const { user, loading, signOut } = useAuth()

  return (
    <main>
      <h1>Catalog Service</h1>
      {loading ? (
        <p>Loading...</p>
      ) : user ? (
        <div>
          <p>Signed in as {user.email}</p>
          <button onClick={signOut}>Sign out</button>
        </div>
      ) : (
        <GoogleSignInButton />
      )}
    </main>
  )
}

export default Home
