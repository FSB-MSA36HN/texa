import { runFixtureControl } from './fixture-control'

export default function globalSetup() {
  runFixtureControl('prepare')
}
