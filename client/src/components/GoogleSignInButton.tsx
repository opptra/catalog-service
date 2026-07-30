import { useEffect, useRef } from 'react'
import { renderSignInButton } from '../auth/google'

function GoogleSignInButton() {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (container) {
      renderSignInButton(container)
    }
    return () => {
      if (container) container.innerHTML = ''
    }
  }, [])

  return <div ref={containerRef} />
}

export default GoogleSignInButton
