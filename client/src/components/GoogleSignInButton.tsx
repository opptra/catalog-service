import { useEffect, useRef } from 'react'
import { renderSignInButton } from '../auth/google'

interface GoogleSignInButtonProps {
  width?: number
}

function GoogleSignInButton({ width = 320 }: GoogleSignInButtonProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (container) {
      void renderSignInButton(container, { width })
    }
    return () => {
      if (container) container.innerHTML = ''
    }
  }, [width])

  return <div ref={containerRef} />
}

export default GoogleSignInButton
