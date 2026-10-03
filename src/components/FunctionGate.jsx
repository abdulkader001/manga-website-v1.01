import useSiteFunctions from "../hooks/useSiteFunctions";

// Shows its children only while the owner has the function switched on.
export default function FunctionGate({ name, children, fallback = null }) {
  const { isOn } = useSiteFunctions();
  return isOn(name) ? children : fallback;
}
