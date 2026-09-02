import {redirect} from "next/navigation";
import {legacyUrl} from "@/lib/paths";

export default function TawjihReviewPage() {
  redirect(legacyUrl("/tawjih-review"));
}
