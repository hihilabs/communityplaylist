// Allows dispatchEvent with CustomEvent without TS error
interface Window {
  dispatchEvent(event: CustomEvent): boolean
}
